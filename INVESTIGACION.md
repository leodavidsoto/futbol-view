# INVESTIGACION.md — el estado del arte, y qué se adopta

Escrito el 2026-08-19. Es un registro de decisión, no una lista de enlaces: cada
apartado dice **qué hace la técnica, qué costaría aquí, y qué se hizo con ella**.
Lo que no se adopta lleva escrito por qué, para que quien lo retome no repita la
evaluación desde cero.

> Regla que se aplicó a todo: **una técnica que no cabe en la máquina del
> usuario no es una mejora, es una promesa.** Este sistema corre hoy en CPU. Lo
> que exija GPU se documenta como lo que es —un camino de futuro— y no se
> presenta como disponible.

---

## 1. Segmentación y seguimiento: SAM 2 y SAMURAI

**Qué son.** SAM 2 (Meta) extiende Segment Anything a vídeo con una memoria que
mantiene la coherencia del objeto entre frames. SAMURAI lo adapta a seguimiento
visual añadiendo un criterio de movimiento a la selección de memoria, lo que le
permite mantener la identidad a través de oclusiones **sin reentrenar**, que es
justamente donde este sistema falla.

**Por qué encaja tan bien con el problema.** El defecto medido aquí es de
identidad, no de detección: 51 identidades para ~22 jugadores. SAM 2 con memoria
es exactamente la familia de soluciones a ese problema.

**Por qué no se adopta todavía.** El coste. SAM 2 mantiene un banco de memoria y
corre un decodificador por frame y por objeto; con veintidós jugadores en CPU
está fuera de escala por órdenes de magnitud. Hoy este sistema ya tiene que
analizar 1 de cada 5 frames con un detector mucho más barato.

**Qué se hizo en su lugar.** Se adoptó la **idea** —resolver la identidad con
información temporal acumulada— en la forma que sí cabe: un post-proceso de
fusión de tracklets (`fcopilot/tracklets.py`). Ver §2.

**Cuándo volver.** Con GPU disponible, SAMURAI sobre los recortes de jugador (no
sobre el frame entero) es el siguiente paso natural, y el punto de entrada ya
existe: `describe()` en los clasificadores devuelve el descriptor de apariencia
que la fusión consume; sustituirlo por un descriptor de SAM 2 no toca nada más.

## 2. Reconstrucción del estado del juego: SoccerNet GSR

**Qué es.** La tarea de SoccerNet *Game State Reconstruction* es exactamente
este producto: seguir e identificar jugadores desde una sola cámara móvil y
situarlos en un minimapa, sin nada puesto en el jugador. El pipeline ganador de
2024 (Constructor Tech, GS-HOTA 63,81 frente a 43,15 del segundo) es modular y
sus dos piezas decisivas son:

1. una red de parámetros de cámara que mapea imagen → coordenadas reales del
   campo;
2. un **post-proceso que refina y une tracklets cortos en trayectorias largas y
   coherentes**, reduciendo mucho la fragmentación y los intercambios de
   identidad.

**Qué se adoptó.** Las dos, en la versión que cabe aquí:

- La fusión de tracklets es `fcopilot/tracklets.py`, con filtros de tiempo,
  física y apariencia. Es la pieza con más impacto por línea escrita de todo
  este trabajo: ataca directamente el 51-por-22.
- El mapeo a coordenadas reales es `fcopilot/pitch.py` + la ruta
  `POST /api/calibrate-landmarks`. Ver §3.

**Lo que no se adoptó.** El reconocimiento de dorsal y el rol (portero,
árbitro). Requiere modelos adicionales y, sobre todo, **resolución en el
jugador**: en la toma elevada que usa este usuario un dorsal ocupa unos pocos
píxeles y no hay nada que leer. Es un problema de cámara antes que de modelo.

## 3. Registro de campo: PnLCalib / «No Bells, Just Whistles»

**Qué es.** Un pipeline que detecta puntos clave del campo —intersecciones de
líneas— y calibra la cámara contra un modelo 3D del campo, con un refinamiento
posterior que usa las líneas detectadas para optimización no lineal. Es hoy el
estándar de facto para esto y es lo que alimenta a los pipelines de §2.

**El problema real que resuelve aquí.** Antes de este trabajo, calibrar exigía
que el usuario **supiera las dimensiones de su campo en metros** y escribiera
cuatro pares de coordenadas del mundo a mano. Nadie hace eso. Y sin calibración,
las distancias salían de una constante de 8 px/m que no tiene nada que ver con
ningún campo — se midió el error: la escala real en la banda donde juegan iba de
25 a 47 px/m.

**Qué se adoptó.** El modelo del campo como dato: `fcopilot/pitch.py` define
dimensiones y ~33 puntos de referencia **con nombre** para fútbol 11, 7 y sala.
Calibrar es ahora señalar «la esquina» y «el punto central», no escribir metros.

**Y lo importante:** `homography_from_landmarks()` acepta el mismo diccionario
`{nombre: [x, y]}` venga de una persona haciendo clic o de un modelo de registro
de campo. **El hueco para automatizarlo está abierto y tiene forma.** Integrar
PnLCalib es escribir un adaptador que produzca ese diccionario; no hay que tocar
nada más.

**Lo que falta para cerrarlo.** Los pesos del modelo de puntos clave y `torch`.
Es el mismo problema de aprovisionamiento que ya tiene el detector, y la
decisión de descargar pesos de terceros es del usuario (ver `PLAN.md` §4).

## 4. Detección: RF-DETR, RT-DETR y el problema del balón

**Qué hay.** RF-DETR (Roboflow, ICLR 2026) es hoy lo mejor en relación
precisión/latencia sobre COCO: RF-DETR-L da 56,5 AP a 6,8 ms en una T4, y la
variante 2XL es el primer modelo en tiempo real que pasa de 60 AP. Usa un
*backbone* DINOv2 y atención deformable multiescala, que es precisamente lo que
ayuda con objetos pequeños.

**Qué se adoptó: nada, todavía, y a propósito.** El cuello de botella de este
sistema **no es la calidad del detector de personas**. Con un modelo específico
de fútbol ya se detectan 23 jugadores por frame de forma estable. Cambiar de
arquitectura mejoraría un número que ya no es el que duele.

**Dónde sí duele: el balón.** A la distancia de estas tomas el balón son unos
cuatro píxeles. Ni YOLO genérico ni el modelo de fútbol probado lo ven de forma
fiable, y eso bloquea posesión, pases y todo lo táctico. Las dos vías reales:

1. **Inferencia por teselas** (*tiling*), que es lo que hace la librería
   `sports` de Roboflow: trocear el frame para que el balón ocupe una fracción
   mayor de cada tesela, con solape y supresión de no-máximos entre teselas.
   **El repositorio ya tiene la pieza** —el modo SAHI—, pero está pensado para
   personas y no para un objeto de cuatro píxeles.
2. **Un modelo específico de balón**, entrenado sólo para eso.

**Qué se hizo mientras tanto:** ser explícito. El panel cuenta en cuántos frames
se vio el balón y **avisa de que la posesión es orientativa** cuando ese
porcentaje baja del 35 %. Una posesión de 48/52 calculada sobre un balón visto
el 12 % del tiempo es un número inventado, y hasta ahora se enseñaba igual.

## 5. Carga externa: la bibliografía de GPS en fútbol

**Qué dice.** Hay consenso razonable en las bandas: alta velocidad 14,4-19,8
km/h, muy alta 19,8-25,2, sprint por encima de 25,2. Y hay un segundo grupo de
métricas que **no** se deducen de la velocidad y que los cuerpos técnicos miran
tanto o más: aceleraciones y frenadas por encima de ±3 m/s², porque concentran
la demanda metabólica y el riesgo de lesión aunque no aparezcan como velocidad
alta. La discusión abierta es umbrales absolutos frente a relativos al máximo de
cada jugador (70 % / 90 %), y hay trabajo reciente a favor de los relativos.

**Qué se adoptó.** Todo (`fcopilot/load.py`): las bandas con esos cortes —antes
eran 7/14/20/25, redondos y sin respaldo—, aceleraciones y frenadas que **no
existían en absoluto**, normalización por minuto observado, y los umbrales
relativos junto a los absolutos.

**Lo que se dice en voz alta.** Cada fabricante de GPS corta las bandas donde
quiere, así que estas cifras no son comparables con las de un GPS sin mirar
antes con qué bandas las cortó. Va escrito en el contrato y en el informe.

---

## Lo que sigue siendo el techo, y no es un modelo

Tres cosas limitan este sistema más que cualquier arquitectura de red:

1. **El balón.** §4. Es un problema de píxeles disponibles antes que de modelo.
2. **La CPU.** `frame_skip` alto es lo que fragmenta los tracks. Con GPU, la
   fusión de tracklets tendría mucho menos que arreglar — y SAMURAI entraría en
   juego.
3. **No hay un partido etiquetado a mano.** Ninguna prueba dice si las métricas
   se parecen a la realidad; sólo que el cálculo hace lo que dice el código y
   que los órdenes de magnitud son plausibles. Es trabajo de campo, no de
   código, y no lo cubre ningún carril (`ANALISIS.md` §0.7). **Mientras eso no
   exista, el panel del DT debe seguir enseñando su bloque de calidad antes que
   sus conclusiones**, que es exactamente para lo que está.

## Fuentes

- [SAMURAI: Adapting Segment Anything Model for Zero-Shot Visual Tracking with Motion-Aware Memory](https://arxiv.org/html/2411.11922v1)
- [SoccerNet Game State Reconstruction: End-to-End Athlete Tracking and Identification on a Minimap](https://openaccess.thecvf.com/content/CVPR2024W/CVsports/papers/Somers_SoccerNet_Game_State_Reconstruction_End-to-End_Athlete_Tracking_and_Identification_on_CVPRW_2024_paper.pdf)
- [From Broadcast to Minimap: Achieving State-of-the-Art SoccerNet Game State Reconstruction](https://arxiv.org/pdf/2504.06357)
- [sn-gamestate — implementación de referencia de SoccerNet GSR](https://github.com/SoccerNet/sn-gamestate)
- [PnLCalib: Sports Field Registration via Points and Lines Optimization](https://arxiv.org/pdf/2404.08401)
- [No Bells, Just Whistles: Sports Field Registration by Leveraging Geometric Properties](https://github.com/mguti97/No-Bells-Just-Whistles)
- [RF-DETR: A SOTA Real-Time Object Detection Model](https://blog.roboflow.com/rf-detr/) · [benchmarks](https://roboflow.github.io/rf-detr/learn/benchmarks/)
- [RT-DETRv2: Improved Baseline with Bag-of-Freebies for Real-Time Detection Transformer](https://arxiv.org/pdf/2407.17140)
- [Ball Tracking in Sports with Computer Vision — inferencia por teselas](https://blog.roboflow.com/tracking-ball-sports-computer-vision/) · [roboflow/sports](https://github.com/roboflow/sports)
- [Physical KPIs in Modern Football: What to Measure and Why — Barça Innovation Hub](https://barcainnovationhub.fcbarcelona.com/blog/physical-kpis-in-modern-football-what-to-measure-and-why/)
- [Sprint in Football: Absolute or Relative Thresholds? (2025)](https://fsi.training/en/sprint-in-football-absolute-or-relative-thresholds/)
- [Monitoring Training Load with GPS: Practical Guidance for Team Sport Coaches](https://www.setantacollege.com/monitoring-training-load-with-gps-practical-guidance-for-team-sport-coaches/)
