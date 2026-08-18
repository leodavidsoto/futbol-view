# ANALISIS.md — intake del proyecto

Producto de la Fase 0 de `PROMPT_ORQUESTACION.md`. Se escribió **antes** de
cortar carriles, leyendo el código como fuente primaria. Donde el código y la
documentación se contradicen, manda el código y la contradicción queda anotada.

**Material leído:** el árbol de `main`, la rama `claude/mejora-suite-completa-0n5sr7`
(PR #1, abierta), `README.md`, `INSTALACION_V2.md`, `QUICK_START.md`, `TESTING.md`
y la suite de tests. **Fecha del intake:** 2026-08-18.

> **Nota de base.** El corte se hace sobre la estructura de la PR #1 —el paquete
> `fcopilot/`—, no sobre `main`. Cortar sobre `main` significaría diseñar
> carriles alrededor de un fichero de 1754 líneas que está a punto de dejar de
> existir. Es una decisión de dos puertas (D-01): si la PR #1 se cerrara sin
> mezclar, el mapa de rutas de `NUCLEO` y `PERCEPCION` habría que rehacerlo.

---

## 0.1 El objetivo, reformulado

**Convertir la grabación de un partido en métricas de rendimiento por jugador y
por equipo, en vivo mientras el vídeo se procesa, sin que hagan falta ni cámaras
especiales ni chalecos GPS.**

Es una herramienta para quien entrena o analiza fútbol amateur y sólo tiene el
vídeo del partido: detecta a los jugadores, los sigue, los reparte en dos
equipos por el color de la camiseta y produce distancia recorrida, velocidades,
sprints, zonas de esfuerzo y posesión. Sustituye a mirar el partido con una
libreta. Si no existe, esos datos simplemente no se tienen: el sistema de
seguimiento óptico profesional cuesta lo que cuesta.

El vídeo se analiza en el servidor y las métricas viajan al navegador según
salen, frame a frame, para que el usuario vea el análisis avanzar sobre su
propio vídeo en vez de esperar a un informe final.

---

## 0.2 Inventario del dominio

**Entidades** (con identidad y ciclo de vida propios):

| Entidad | Identidad | Vive en |
|---|---|---|
| **Sesión de análisis** | `session_id` que da el cliente | `fcopilot/sessions.py`, persistida en `.session_state/<id>.json.gz` |
| **Jugador seguido (track)** | `track_id` que asigna el tracker | `PlayerKinematics` dentro del analizador |
| **Partido / informe** | derivado de la sesión | `fcopilot/report.py` |
| **Calibración de campo** | una homografía por sesión | `fcopilot/geometry.py` |

Datos de otra entidad, sin identidad propia: la **muestra** (`Sample`: frame,
tiempo, píxel, mundo), el **frame de resultado** que viaja por NDJSON, la
**configuración de runtime** (pertenece a la sesión), el **equipo** (vocabulario
cerrado de tres valores, no una entidad).

**Capacidades:** analizar un vídeo subido; analizar un frame suelto de webcam;
calibrar el campo con cuatro puntos; renombrar un jugador; corregir su equipo;
cambiar la configuración de detección y tracking; pedir el informe; exportar los
datos crudos; reiniciar la sesión (duro o blando); listar y borrar sesiones.

**Actores:** el navegador de una persona (único actor real hoy); el proceso de
arranque de FastAPI (`lifespan`), que restaura sesiones de disco; el barrido de
sesiones caducadas por TTL. **No hay ningún actor autenticado**, que es el
hallazgo central de este intake.

**Integraciones externas** (todo lo que puede faltar, caducar o cambiar de
contrato): `ultralytics` (YOLOv11), `sahi`, `norfair`, `supervision`/ByteTrack,
`torch` + los pesos de OSNet, `opencv`. Las seis están importadas de forma
opcional y con bandera de disponibilidad — es una decisión de diseño explícita,
no un accidente. Fuera del proceso: el fichero de pesos `yolo11x.pt`, que nadie
provisiona y que el sistema da por presente.

---

## 0.3 Catálogo de requisitos

`Origen` dice de dónde sale cada fila: **código** = se puede señalar la línea;
**docs** = está escrito en la documentación del repo; **inferido** = lo deduje,
y la fila dice de qué; **ausente** = nadie lo pidió pero el sistema no puede no
tenerlo, y lo escribo yo para que se pueda tachar a la vista.

### Funcionales

| ID | Requisito | Tipo | Origen | Confianza |
|----|-----------|------|--------|-----------|
| R-01 | Detectar jugadores y balón en cada frame procesado | funcional | código (`fcopilot/detection.py`) | alta |
| R-02 | Mantener la identidad de cada jugador entre frames | funcional | código (`analyzer._track_players`) | alta |
| R-03 | Asignar cada jugador a `team_1`/`team_2` de forma estable en el tiempo | funcional | código (`fcopilot/teams.py`) | alta |
| R-04 | Calcular distancia recorrida y velocidad instantánea y punta por jugador | funcional | código (`fcopilot/kinematics.py`) | alta |
| R-05 | Calcular posesión por equipo en segundos reales de juego | funcional | código (`fcopilot/possession.py`) | alta |
| R-06 | Permitir nombrar jugadores y corregir su equipo a mano | funcional | código (`/api/player-name`, `/api/player-team`) | alta |
| R-07 | Calibrar el campo con cuatro puntos y dar métricas en metros reales | funcional | código (`fcopilot/geometry.py`) | alta |
| R-08 | Emitir el análisis en streaming NDJSON mientras el vídeo se procesa | funcional | código (`/api/process-video`) | alta |
| R-09 | Producir un informe agregado por jugador y por equipo (sprints, zonas) | funcional | código (`fcopilot/report.py`) | alta |
| R-10 | Exportar los datos crudos del partido, con o sin posiciones | funcional | código (`/api/export`) | alta |
| R-11 | Reproducir el vídeo en el cliente sincronizado con sus métricas | funcional | código (`frontend/src/lib/frames.js`) | alta |
| R-12 | Configurar el runtime (modelo, tracker, umbrales) desde la interfaz | funcional | código (`/api/config`) | alta |
| R-13 | Aislar el estado por sesión: dos pestañas no se pisan los datos | funcional | código (`fcopilot/sessions.py`) | alta |

### Transversales

| ID | Requisito | Tipo | Origen | Confianza |
|----|-----------|------|--------|-----------|
| R-14 | Toda métrica se calcula sobre tiempo de vídeo real, nunca sobre FPS de procesado | transversal | código (`Sample.t`, `process_video`) | alta |
| R-15 | Ningún dato de una sesión es accesible desde otra | transversal | inferido de que R-13 exista: aislar el estado sin aislar el acceso no aísla nada | **baja** |
| R-16 | El servicio arranca y responde sin las dependencias pesadas; el fallo se reporta al usar, no al importar | transversal | código (`DetectorUnavailable`, banderas `*_AVAILABLE`) | alta |
| R-17 | Sólo se cargan pesos de modelo situados bajo `MODEL_ROOT` | transversal | código (`validate_model_path`) | alta |
| R-18 | Ningún agente toca ficheros de un carril que no le fue asignado | transversal | inferido del encargo de orquestación | alta |

### Reglas de dominio

| ID | Requisito | Tipo | Origen | Confianza |
|----|-----------|------|--------|-----------|
| R-19 | Vocabularios cerrados de tracker, modo de detección, clasificador y equipo manual | regla-de-dominio | código (`ALLOWED_*` en `config.py`) | alta |
| R-20 | Zonas de intensidad como tabla: caminando / trote / carrera / alta intensidad / sprint | regla-de-dominio | código (`SPEED_ZONES`) | alta |
| R-21 | Cada parámetro de configuración tiene un rango válido y se rechaza fuera de él | regla-de-dominio | código (`_NUMERIC_BOUNDS`) | alta |
| R-22 | Un desplazamiento por encima de `max_speed_kmh` es cambio de identidad del tracker, no movimiento: no acumula distancia | regla-de-dominio | código (`PlayerKinematics.update`) | alta |

### Operativos

| ID | Requisito | Tipo | Origen | Confianza |
|----|-----------|------|--------|-----------|
| R-23 | CI en verde en cada push: backend y frontend | operativo | código (`.github/workflows/ci.yml`) | alta |
| R-24 | El estado de una sesión sobrevive a un reinicio del backend | operativo | código (`SessionManager.save`/`_restore`) | alta |
| R-25 | Las sesiones caducan por TTL y hay un tope de sesiones vivas | operativo | código (`SESSION_TTL_SECONDS`, `MAX_SESSIONS`) | alta |
| R-26 | Los pesos del modelo tienen que existir en la máquina antes de analizar | operativo | docs (`INSTALACION_V2.md`) | media |

### Ausentes — nadie los pidió y el sistema no puede no tenerlos

| ID | Requisito | Tipo | Origen | Confianza |
|----|-----------|------|--------|-----------|
| R-27 | Autenticar a quien llama antes de darle acceso a una sesión | transversal | **ausente** | media |
| R-28 | Limitar el consumo por cliente: tamaño total subido, subidas concurrentes, frecuencia | operativo | **ausente** | media |
| R-29 | Provisión reproducible del entorno de ejecución: imagen, pesos, versión de CUDA | operativo | **ausente** | alta |
| R-30 | Política de retención y borrado de los vídeos y de los datos derivados | operativo | **ausente** | **baja** |

---

## 0.4 Restricciones transversales y su guardia

Ninguna de estas me la dieron: salen del catálogo. La columna del medio es la
que decide si la restricción puede quedarse en la documentación o necesita un
guardia en el código.

| Restricción | Qué pasa si alguien la olvida | Guardia | Dónde vive |
|---|---|---|---|
| **La sesión es la frontera de aislamiento** (R-13, R-15) | Nada visible. Una ruta nueva que lea el diccionario de sesiones directamente en vez de por `Depends(get_session_id)` filtra datos entre sesiones y ningún test lo nota | Que no exista forma de obtener un analizador sin pasar por la dependencia: `SessionManager` sin acceso público al diccionario interno, y un test que recorra las rutas de FastAPI y falle si alguna no declara la dependencia de sesión | `fcopilot/sessions.py` + `tests/test_api.py` — **por construir**, hoy la regla es una convención |
| **El tiempo de vídeo es la base de toda métrica** (R-14) | Nada visible, y las velocidades salen multiplicadas por el factor de `frame_skip`. Es exactamente el bug que la PR #1 arregló: se puede reintroducir con una llamada | Que `Sample` no se pueda construir sin `t`, y que `PlayerKinematics.update` rechace una muestra cuyo `t` no avance respecto de la anterior | `fcopilot/kinematics.py` — **parcial**: `t` es obligatorio, pero un `t` derivado del reloj de pared se acepta sin protesta |
| **Sólo se cargan pesos bajo `MODEL_ROOT`** (R-17) | Un `.pt` es un pickle: cargar uno arbitrario es ejecución de código. Sin el guardia, cualquiera que pueda llamar a `/api/config` elige qué se ejecuta | `Path.is_relative_to` sobre la ruta resuelta, ya implantado en la PR #1 | `football_copilot_v2_backend.py:237` — **hecho** |
| **Las dependencias pesadas son opcionales** (R-16) | El servidor deja de arrancar en cualquier entorno sin GPU, y la suite pasa de segundos a gigabytes | Que CI corra en un entorno que *no* tiene esas dependencias, y por tanto un `import` obligatorio nuevo rompa el build | `.github/workflows/ci.yml` — **hecho**, y es un guardia elegante: la ausencia es la prueba |
| **Un agente = un carril** (R-18) | Nada, hasta que dos agentes editan el mismo fichero en paralelo y uno pierde su trabajo | Mapa de propiedad en `carriles.json` + `tools/check_carriles.py` sobre el diff | `tools/check_carriles.py` — **construido en este turno** |

Las dos primeras filas son las que justifican los carriles `API` y `NUCLEO`:
tienen la regla escrita y el guardia sin construir.

---

## 0.5 Registro de ambigüedades

**Una puerta** (equivocarse cuesta rehacer trabajo hecho o migrar datos
escritos) — **te las pregunto y paro**:

| ID | La duda | Por qué es de una puerta | Mi recomendación |
|----|---------|--------------------------|------------------|
| A-01 | ¿Esto va a estar expuesto en internet, o corre en la máquina de quien lo usa? | Decide si R-27 es un carril de trabajo o una nota en el README. Un servicio público sin autenticación con subida de 1 GB no se puede desplegar; el mismo binario en `localhost` no tiene el problema | Asumir **local por ahora**, y que `OPERACION` cierre la frontera antes de cualquier despliegue público |
| A-02 | ¿Los vídeos subidos se pueden guardar, o hay que borrarlos al terminar? | Es dato de personas identificables jugando. Decidirlo después significa migrar o borrar lo ya acumulado, y quizá haber incumplido mientras tanto | Borrar el vídeo al terminar el análisis (ya se hace) y **no persistir nunca el vídeo**, sólo las métricas |
| A-03 | ¿El sistema tiene que servir a varias personas a la vez, o a una? | `MAX_SESSIONS=12` y `WORKER_THREADS=2` dicen «varias», pero sin autenticación no hay forma de que sean personas distintas. La respuesta cambia el corte de `API` | Una persona, varias pestañas. Si son varias personas, R-27 sube a la ola 1 |
| A-04 | ¿Cuál es la unidad de éxito: el partido entero o el clip? | Un partido de 90 minutos a 1 de cada 3 frames son ~54.000 muestras por jugador; `MAX_TRACK_HISTORY`/`max_history=300` dice que se diseñó para clips. Si el objetivo es el partido, el modelo de almacenamiento no da y hay que rehacerlo, no ajustarlo | **Clips de hasta ~10 minutos**, y decirlo en la documentación en vez de que el usuario lo descubra |
| A-05 | ¿Borro `FootballCopilot_v2.jsx` de la raíz? | Ya está marcado como histórico y divergiendo. Es de una puerta sólo porque borrar código es irreversible en la práctica | Borrarlo. Mientras decides, lo he **congelado**: el guardia rechaza cualquier cambio en él |

**Dos puertas** (decidido por ti, anotado, reversible) — **no paro por estas**:

| ID | Decisión | Qué la revierte |
|----|----------|-----------------|
| D-01 | Cortar sobre la estructura de la PR #1 (`fcopilot/`) y no sobre `main` | Rehacer el mapa de rutas de `NUCLEO` y `PERCEPCION` en `carriles.json`; el resto del andamiaje no cambia |
| D-02 | Seis carriles, con `PLATAFORMA` como infraestructura de gobierno | Fusionar `PLATAFORMA` en `API` si resulta que nadie corre el guardia |
| D-03 | La fuente de verdad del corte es `carriles.json`, y `CARRILES.md` lo renderiza | Invertirlo, con `CARRILES.md` como fuente y un parser de markdown; se pierde robustez y se gana un fichero menos |
| D-04 | `fcopilot/config.py` es de `API`, no de `NUCLEO`, aunque contenga constantes de dominio | Moverlo a `NUCLEO` y que `API` pida las claves nuevas; cambia una línea del manifiesto |
| D-05 | `fcopilot/analyzer.py` es de `PERCEPCION`: manda el bucle de frames, no la definición de métrica | Partir `analyzer.py` en bucle (PERCEPCION) y ensamblador de métricas (NUCLEO) si el fichero se vuelve el punto de fricción |
| D-06 | Cada carril es dueño de su directorio `worklog/<CARRIL>/`, y `EVENTS.jsonl` es de sólo añadir para todos | Un fichero de eventos por carril; se pierde el orden global, que es lo que hace útil el relevo |

---

## 0.6 Tablas de dominio

Ya están implementadas **como dato**, que es como deben estar. Se listan aquí
porque son fuente de verdad y el código no puede contradecirlas.

**Zonas de intensidad** (`SPEED_ZONES`, `fcopilot/kinematics.py`) — mínimo
inclusive, máximo exclusivo:

| Zona | km/h desde | km/h hasta |
|---|---|---|
| `caminando` | 0 | 7 |
| `trote` | 7 | 14 |
| `carrera` | 14 | 20 |
| `alta_intensidad` | 20 | 25 |
| `sprint` | 25 | ∞ |

**Vocabularios cerrados** (`fcopilot/config.py`): trackers `bytetrack`,
`norfair`, `simple`; modos de detección `normal`, `sahi`; clasificadores de
equipo `kmeans`, `grass_kmeans`, `osnet`; equipos asignables a mano `team_1`,
`team_2`, `unknown`.

**Máquina de estados de la posesión** (inferida de `PossessionTracker`; no está
dibujada en ningún sitio, la dibujo yo):

```
           rival mantiene el balón           rival mantiene el balón
           confirm_frames seguidos           confirm_frames seguidos
   team_1 ──────────────────────► none ◄────────────────────── team_2
      ▲                            │                              ▲
      └────────────────────────────┴──────────────────────────────┘
            un solo frame del rival NO cambia el portador (histéresis)
```

La transición directa `team_1 → team_2` sí existe si el rival encadena
`confirm_frames`. **Pregunta abierta para quien tome `NUCLEO`:** ¿debería un
cambio de posesión pasar siempre por `none`? Hoy no pasa, y eso hace que el
contador `changes` cuente robos y pérdidas juntos.

**Estados de un carril** (fuente de verdad de este andamiaje, no del producto):
`NO_INICIADO` → `EN_CURSO` → `LISTO_PARA_REVISION` → `HECHO`, más `BLOQUEADO`
fuera de la línea. Implementada como dato en `PLANTILLAS.md` y verificada por el
guardia.

---

## 0.7 Lo que no encontré

Lo busqué en el código y en la documentación y no está. No es un reproche: es lo
que hay que averiguar mientras los carriles avanzan.

- **Quién usa esto y en qué máquina.** No hay `Dockerfile`, ni `docker-compose`,
  ni notas de despliegue. `INSTALACION_V2.md` describe un arranque manual en la
  máquina de quien desarrolla.
- **Volumen y latencia esperados.** No hay ninguna cifra objetivo. `WORKER_THREADS=2`
  y `MAX_SESSIONS=12` son valores por defecto, no un dimensionamiento.
- **Precisión aceptable.** No hay ni un dato de referencia ni un vídeo de prueba
  con métricas conocidas. Toda la suite prueba que el cálculo hace lo que dice
  el código, ninguna prueba que el resultado se parezca a la realidad. **Es el
  agujero más importante del proyecto** y no lo cubre ningún carril: hace falta
  un partido etiquetado a mano, y eso es trabajo de campo, no de código.
- **De dónde salen los pesos.** `yolo11x.pt` y `osnet_x1_0_imagenet.pth` se dan
  por presentes. Nada los descarga ni verifica su hash.
- **Qué pasa con los datos que ya existen.** `.session_state/` acumula sesiones
  comprimidas sin política de borrado más allá del TTL en memoria.
- **Plazos y presupuesto.** No hay ninguno declarado, así que las olas se
  ordenan por dependencia técnica y no por valor de negocio. Si hay una fecha,
  dímela: cambia el orden.

---

## Contradicciones detectadas

- **`INSTALACION_V2.md` (en `main`) contra el código:** manda `npm start` en el
  puerto 3000 y editar un `.jsx` de la raíz que no forma parte de la aplicación.
  La aplicación real es Vite en el 5173 y la interfaz viva es
  `frontend/src/App.jsx`. **Corregido en la PR #1**; queda anotado porque
  explica por qué `FootballCopilot_v2.jsx` sigue en la raíz.
- **`MAX_TRACK_HISTORY` contra el objetivo declarado:** el informe promete
  métricas de partido y el almacenamiento está dimensionado para clips (A-04).
- **`MAX_SESSIONS=12` contra la ausencia de autenticación:** el sistema está
  preparado para varios usuarios simultáneos y no tiene forma de distinguirlos
  (A-03, R-27).
