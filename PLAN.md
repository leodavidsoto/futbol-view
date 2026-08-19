# PLAN.md — relevo y siguiente ola

Escrito al cerrar la sesión del 2026-08-19. Quien retome empieza por aquí, sigue
por `AGENTS.md` y luego por el `STATE.md` de su carril.

> El estado real de cada carril está en `worklog/EVENTS.jsonl`, que es el que
> manda. Este documento es la vista de orquestación: qué se puede despachar
> ahora, qué bloquea a qué, y por qué.

---

## 1. Dónde está el proyecto

| Carril | Estado | Contrato |
|---|---|---|
| `PLATAFORMA` | `LISTO_PARA_REVISION` | v1 |
| `NUCLEO` | `LISTO_PARA_REVISION` | v1 |
| `PERCEPCION` | `LISTO_PARA_REVISION` | v1 |
| `API` | `LISTO_PARA_REVISION` | v1 |
| `CLIENTE` | `EN_CURSO` | v1 |
| `OPERACION` | `EN_CURSO` | v1 |

360 pruebas de backend, 115 de frontend, CI en verde, `check_carriles` y
`check_cobertura` sin hallazgos.

**Ninguno de los cuatro `LISTO_PARA_REVISION` es `HECHO`**: falta la revisión
cruzada, que por diseño la hace un agente que no los implementó. Ese es el
primer trabajo disponible y no depende de nada.

### Lo que ya funciona de verdad

El sistema se levantó y se probó con dos vídeos reales de un partido. Con un
modelo de fútbol, resolución completa, calibración y zona de juego: 23 jugadores
por frame, distancias de 5,7 a 9,8 km/h de media por jugador —realistas—,
posesión 48/52, balón a 1,67 m del jugador más cercano, y ni un error en el
stream. El recorrido completo está en `INSTALACION_V2.md` §9 bis.

---

## 2. Hallazgos de la revisión cruzada de código

Diez hallazgos sobre el diff completo. Tres ya están corregidos; los siete
restantes se reparten abajo. **Ninguno tiene todavía una prueba que lo fije**:
escribirla es parte del trabajo, no un extra.

### Corregidos en esta sesión

| Gravedad | Qué era |
|---|---|
| **alta** | `/ws/stream` construía la sesión —analizador y modelo incluidos— *antes* de comprobar la credencial, así que una conexión no autenticada consumía memoria y podía desalojar la sesión de otro. La comprobación va ahora primero |
| media | `docker-compose.yml` pasaba `API_KEY` como `VITE_API_KEY`, y Vite hornea sus variables en el bundle: publicaba la credencial del servidor a cualquiera que abriera el JS, anulando la autenticación que el propio fichero pide activar |
| baja | `play_area` y `discarded_outside` estaban duplicadas en el diccionario de `stats`; el par muerto emitía el polígono del campo en cada frame del stream |

### Pendientes, por carril

**`API`** — tres:

1. **`TimeBaseError` no se maneja en ninguna ruta.** Después de analizar un
   vídeo en una sesión, abrir el WebSocket en **esa misma sesión** lanza en el
   primer frame —vídeo y reloj no se mezclan, y eso es correcto— pero el socket
   se cierra sin decir nada, y como el estado se persiste, la sesión queda rota
   para siempre. Hay que capturarlo y responder algo accionable: «esta sesión ya
   tiene métricas de vídeo; reinicia antes de usar la cámara».
2. **`/health?session_id=mal!id` devuelve 500.** `SessionIdError` no se captura
   en la única ruta abierta sin credencial. Debe ser un 400.
3. **Carrera al guardar la sesión** (`sessions.py`): dos `save()` concurrentes de
   la misma sesión escriben el mismo `.gz.tmp`; el fichero publicado puede
   quedar corrupto y la sesión restaura vacía en silencio. El temporal necesita
   un sufijo único.

**`PERCEPCION`** — tres:

4. **`apply_config` reinicia el tracker sin limpiar `self.tracks`.** Los IDs
   vuelven a empezar en 1, así que un jugador nuevo hereda la cinemática, el
   nombre y el equipo de otro. Es de los que producen datos plausibles y falsos.
5. **`load_state` fija `_t_origin = 0.0`.** Una sesión de webcam restaurada
   calcula `t = time.monotonic()` y suma de golpe el tiempo de arranque de la
   máquina a los segundos de posesión y al tiempo activo.
6. **`teams._fit_features` sólo reinicia `_since_fit` cuando el ajuste tiene
   éxito.** Si los dos centroides se quedan más cerca que `min_separation`, se
   lanza un KMeans completo en **cada** `predict()` —unas 22 por frame— y
   `_features` crece sin límite.

**`CLIENTE`** — dos:

7. **El POST de calibración se dispara dentro del actualizador de
   `setCalibPoints`**, así que en desarrollo con StrictMode se envía dos veces.
8. **`onPlay={() => mode === "ws" && startSendingFrames()}` nunca es cierto**:
   `mode` sólo vale `"video"` o `"webcam"`. Los frames de la webcam **no se
   envían nunca**. Viene de antes de todo este trabajo y por eso el revisor no
   lo contó como hallazgo del diff, pero es un modo entero que no funciona.

---

## 3. Qué despachar ahora

**Todo lo de abajo se puede hacer en paralelo:** ningún carril depende del
contrato de otro, porque los seis están publicados.

| Prioridad | Trabajo | Carril |
|---|---|---|
| 1 | **Revisión cruzada** de los cuatro carriles en `LISTO_PARA_REVISION` | cualquiera que no los implementó |
| 2 | Hallazgos 1-3 | `API` |
| 3 | Hallazgos 4-6 | `PERCEPCION` |
| 4 | Terminar el troceado de `App.jsx` + hallazgos 7-8 | `CLIENTE` |
| 5 | Construir la imagen y automatizar el recorrido de extremo a extremo | `OPERACION` |

La revisión cruzada va primero porque los otros cuatro carriles no pueden
declararse `HECHO` sin ella, y porque un hallazgo suyo puede cambiar lo demás.

### Lo que de verdad mejoraría el producto

Por encima de la deuda de arriba, y por orden de impacto sobre lo que el usuario
ve:

1. **Detección del balón.** Es lo que bloquea posesión, pases y todo lo táctico.
   Un balón a esa distancia son cuatro píxeles; ni YOLO genérico ni el modelo de
   fútbol que probamos lo ven de forma fiable, y la zona de juego sólo evita los
   falsos positivos del entorno. Necesita un modelo específico de balón o una
   cámara más cerca.
2. **Fragmentación de tracks.** 51 identidades para ~22 jugadores, porque en CPU
   hay que analizar 1 de cada 5 frames. Con GPU, o con `yolo11n`, el
   `frame_skip` baja y el tracker asocia bien. Es la causa del reparto de
   equipos desequilibrado (35/17 cuando debería ser mitad y mitad).
3. **Un partido etiquetado a mano.** Sigue sin existir, así que **ninguna prueba
   dice si las métricas se parecen a la realidad** (`ANALISIS.md` §0.7). Todo lo
   que sabemos es que el cálculo hace lo que dice el código y que los órdenes de
   magnitud son plausibles. Es trabajo de campo, no de código, y no lo cubre
   ningún carril.

---

## 4. El entorno, para reproducir

Nada de esto está versionado —los pesos pesan cientos de megas y las
dependencias son gigabytes— así que quien retome lo monta otra vez:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install ultralytics norfair sahi
python3 scripts/fetch_weights.py --dest ./weights      # yolo11x, con hash verificado
```

**El modelo que funciona con material real no es `yolo11x`.** Se probaron dos
modelos públicos de detección de jugadores; el que dio mejor resultado fue
`mobadam/football-player-detection` de HuggingFace (clases `ball`, `player`,
`referee`, `goalkeeper`). No está versionado ni tiene hash fijado en
`scripts/weights.sha256.json`: **es un `.pt` de terceros y cargarlo ejecuta
código**, así que la decisión de usarlo la tomó el usuario explícitamente en su
momento y quien retome debería confirmarla, no darla por hecha.

Configuración que produjo los resultados buenos:

```json
{"model": "weights/futbol-mobadam.pt", "person_class": 1, "ball_class": 0,
 "detection_mode": "normal", "tracker_type": "norfair", "norfair_dist": 70,
 "confidence": 0.20, "imgsz": 1920, "frame_skip": 4,
 "process_width": 1920, "process_height": 1080}
```

Más la calibración por homografía y la zona de juego, ambas por sesión.

**Cómo se calibró sin conocer el campo:** midiendo la altura en píxeles de 275
jugadores en 15 frames y asumiendo 1,75 m por jugador. Para una cámara que mira
a un plano, esa altura crece linealmente con la fila de la imagen, y de ahí sale
la escala local y el mapa a metros. Salió R²=0,81 y una escala de 25 a 47 px/m
en la banda donde juegan —la app usaba una constante de 8—. Validación
independiente: el ancho de la zona de juego medido así da 31,8 m, que encaja con
un campo de fútbol 7.

---

## 5. Lo que sigue esperando respuesta humana

Las cinco ambigüedades de una puerta de `ANALISIS.md` §0.5 siguen abiertas. La
que más pesa con diferencia:

- **A-01 — ¿esto se expone fuera de la máquina de quien lo usa?** La credencial
  existe y viene apagada. Lo que **no** está resuelto es que `session_id` siga
  sin ser identidad: dos clientes con la misma credencial se ven las sesiones
  entre sí, y `/api/sessions` las enumera todas. Si la respuesta es «expuesto»,
  eso es trabajo de verdad, no una variable de entorno.
- **A-05 — ¿se borra `FootballCopilot_v2.jsx`?** Sigue congelado por el guardia.
