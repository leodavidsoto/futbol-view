# CUERPO_TECNICO.md — qué gestiona un cuerpo técnico, y qué de eso puede dar esta app

Este documento existe para que la interfaz se organice **por el trabajo de quien
la usa**, y no por la forma que tienen nuestras estructuras de datos. Y para
poner por escrito, antes de construir nada, qué no vamos a poder darles nunca
con una cámara.

---

## 1. Quién es «el cuerpo técnico»

No es una persona. Son cinco o seis, con preguntas distintas y ritmos distintos.

| Rol | Su pregunta | Cuándo la hace |
|---|---|---|
| **Entrenador principal** | ¿A quién cambio? ¿Estamos jugando como queremos? | En el partido, y el lunes |
| **Segundo entrenador** | ¿Se cumple el plan? ¿Qué corregimos el martes? | Después del partido |
| **Preparador físico** | ¿Quién ha acumulado carga? ¿Quién está en riesgo? | Todos los días |
| **Analista** | ¿Qué patrones se repiten? ¿Qué le enseño en vídeo? | Entre partidos |
| **Fisioterapeuta / médico** | ¿Quién está disponible? ¿Cómo vuelve el lesionado? | Todos los días |
| **Entrenador de porteros** | Lo suyo, que esta app no ve | — |

Y trabajan sobre un ciclo: el **microciclo**, la semana entre dos partidos.
Partido → recuperación → carga → activación → partido. Cada día tiene una
intención y una carga previstas, y el cuerpo técnico ajusta según lo que pasó.
Eso significa que **una app que sólo dice cosas el día del partido sirve para
una quinta parte de su trabajo**.

## 2. Las aristas, una por una

### 2.1 Disponibilidad
Quién puede jugar: lesionados, sancionados, cargados. **Es lo primero que se
mira cada día.** No sale de un vídeo: sale del parte médico y del acta.

### 2.2 Carga externa
Cuánto ha corrido cada uno y a qué intensidad, acumulado por sesión y por
semana. La ratio entre la carga aguda (esta semana) y la crónica (el último mes)
es el indicador clásico de riesgo.

### 2.3 Carga interna
Lo que le costó **a él**: RPE, frecuencia cardíaca, variabilidad, cuestionarios
de sueño y fatiga. Dos jugadores que corren lo mismo no se cansan igual. **Una
cámara no ve nada de esto.**

### 2.4 Rendimiento individual
Físico (lo de 2.2) y técnico: pases, duelos, conducciones, decisiones.

### 2.5 Comportamiento colectivo
Cómo se mueve el equipo como bloque: amplitud, profundidad, longitud, cuánto se
estira, dónde pone la última línea, si las líneas se separan. **Es la mitad del
trabajo de un entrenador y es lo que menos herramientas tiene** en el fútbol no
profesional.

### 2.6 Ocupación del espacio
Dónde está cada uno realmente, frente a dónde debería. Mapas de calor por
jugador y por equipo, por carriles y por alturas.

### 2.7 Balón parado
Córners, faltas, saques. A favor y en contra.

### 2.8 Rival
Sus patrones, sus debilidades. Requiere analizar sus partidos.

### 2.9 Decisiones en partido
Cambios, ajustes tácticos. Con información de **ahora**, no del lunes.

### 2.10 Histórico
Comparar contra uno mismo a lo largo de la temporada. Un número suelto no dice
nada; una tendencia sí.

---

## 3. Qué de todo eso puede dar ESTA app

La regla que se aplicó: **si no lo podemos medir de forma honesta, no lo
enseñamos**, ni siquiera en gris. Un hueco se ve; un número inventado no.

| Arista | ¿Podemos? | Con qué |
|---|---|---|
| 2.2 Carga externa | **Sí, hoy** | `load.py`: bandas, aceleraciones, por minuto, caída |
| 2.5 Comportamiento colectivo | **Sí, hoy** | `collective.py`: forma del bloque desde posiciones |
| 2.6 Ocupación del espacio | **Sí, hoy** | Rejilla de zonas desde posiciones |
| 2.4 Rendimiento individual (físico) | **Sí, hoy** | Perfil por jugador |
| 2.9 Decisiones en partido | **Sí, hoy** | Semáforo del panel |
| 2.10 Histórico | **Con trabajo** | Falta persistir partidos y compararlos |
| 2.4 Rendimiento individual (técnico) | **Con trabajo grande** | Necesita el balón, que hoy no se ve |
| 2.7 Balón parado | **Con trabajo grande** | Necesita balón y detección de eventos |
| 2.8 Rival | **Con trabajo grande** | Es analizar otro vídeo; el pipeline vale |
| 2.1 Disponibilidad | **No** | Es dato médico y administrativo |
| 2.3 Carga interna | **No, nunca** | Una cámara no mide un RPE ni un pulso |

### El hallazgo que decide el diseño

**Todo lo colectivo se calcula con las posiciones, sin balón.** Amplitud,
profundidad, longitud del bloque, superficie, compacidad, altura de las líneas,
distancia entre ellas, ocupación de zonas: nada de eso necesita saber dónde está
la pelota.

Y el balón es exactamente lo que este sistema mide peor —a esta distancia son
cuatro píxeles—. Así que **la parte más valiosa para un entrenador es también la
que podemos medir mejor**, y es la que faltaba entera.

### Lo que hay que decir en voz alta, y la interfaz lo dice

1. **Sin calibración, nada de esto son metros.** Las métricas colectivas en
   píxeles no significan nada: una amplitud de «340» no se compara con nada. Sin
   homografía, el bloque táctico **no se enseña**.
2. **La asignación de equipos es poco fiable.** Se midió repartiendo 35/17
   cuando debía ser mitad y mitad. Una métrica de equipo calculada sobre un
   reparto malo es una métrica mala, y va marcada.
3. **No sabemos hacia dónde ataca cada equipo.** Con una cámara y sin detectar
   porterías, «línea defensiva» no se puede afirmar. Lo que sí se puede decir es
   «línea más retrasada» y «más adelantada», que es cierto sin saber la
   dirección. Si el usuario indica la dirección de ataque, pasan a llamarse
   defensiva y ofensiva.
4. **La carga interna no existe aquí.** No hay pestaña de fatiga percibida
   porque no hay dato, y una casilla vacía invita a rellenarla a ojo.

---

## 4. Cómo se organiza la interfaz

Por **pregunta**, no por origen del dato. Cuatro secciones, en el orden en que
se consultan:

| Sección | Quién la mira | Qué responde |
|---|---|---|
| **Partido** | Entrenador, en la banda | ¿Me fío? ¿A quién cambio? ¿Quién no corre? |
| **Físico** | Preparador físico | Carga por jugador: bandas, aceleraciones, por minuto |
| **Colectivo** | Entrenador y segundo | Forma del bloque, ocupación del campo, líneas |
| **Jugador** | Todos | El detalle de uno: perfil, zonas, evolución |

Encima de las cuatro, siempre, la franja de calidad: **si los datos no se
sostienen, eso se lee antes que cualquier conclusión.**

## 5. Lo que falta para cubrir el resto

Por orden de lo que más cambiaría el producto:

1. **Persistir partidos y compararlos.** Sin histórico no hay carga aguda frente
   a crónica, que es el indicador de riesgo que de verdad usa un preparador
   físico. Es trabajo de almacenamiento, no de visión: **es lo más barato de
   todo lo que falta y lo que más aporta.**
2. **Detección de balón.** Desbloquea posesión de verdad, pases, y con ello casi
   todo lo técnico. Es el techo del sistema (`INVESTIGACION.md` §4).
3. **Plantilla de verdad**: nombres, dorsales, posiciones. Hoy los jugadores son
   `#1`, `#2`. Un panel que no dice nombres no lo usa nadie dos veces.
4. **Un partido etiquetado a mano**, sin el cual nada de esto está validado
   contra la realidad (`ANALISIS.md` §0.7).

## Fuentes

- [Microcycles in football: weekly structure from MD-5 to MD+1 — Barça Innovation Hub](https://barcainnovationhub.fcbarcelona.com/blog/microcycles-in-football-weekly-structure-from-md-5-to-md1/)
- [What is a soccer coaching staff, and how does it work? — FSI](https://fsi.training/en/blogs/football-technical-staff-roles)
- [Navigating team tactical analysis in football: an analytical pipeline leveraging player tracking technology (2025)](https://journals.sagepub.com/doi/10.1177/17543371251392456)
- [Length, width and centroid distance as measures of teams' tactical performance in youth football](https://www.researchgate.net/publication/259825216_Length_width_and_centroid_distance_as_measures_of_teams_tactical_performance_in_youth_football)
- [Defensive Line Height: The Metric Defining Modern Defending](https://the-footballanalyst.com/defensive-line-height-the-metric-defining-modern-defending/)
- [The analysis of team tactical behaviour in football using GNSS positional data](https://researchonline.ljmu.ac.uk/id/eprint/19091/1/2022guangzezhangmphil.pdf)
