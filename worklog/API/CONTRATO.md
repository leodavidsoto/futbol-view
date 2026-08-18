# Contrato de API

**Versión:** 1 · **Publicado:** 2026-08-18 · **Estable desde:** 2026-08-18

Consume `NUCLEO` v1 y `PERCEPCION` v1. Es la frontera entre el mundo y el
análisis.

## El `session_id`

Todo el estado —jugadores, nombres, equipos, calibración, métricas— vive dentro
de una sesión. El identificador viaja en la cabecera `X-Session-Id` o en el
parámetro `session_id`; si falta, se usa `"default"`.

Formato: `[A-Za-z0-9_-]{1,64}`. Cualquier otra cosa es 400.

> **Lo que este contrato NO garantiza, y hay que leerlo entero:** el
> `session_id` **lo elige el cliente**. No es un secreto, no se firma y no se
> comprueba contra nada. Quien conozca o adivine el identificador de otro
> partido lee sus datos. Sin `API_KEY` configurada, esa es toda la separación
> que hay. Ver A-01 en `ANALISIS.md`.

## Credencial (opcional)

| | |
|---|---|
| Variable | `API_KEY` |
| Sin definir | **servicio abierto**; se registra un aviso al arrancar |
| Definida | toda ruta bajo `/api` y el WebSocket exigen `X-Api-Key` o `?api_key=` |
| Excepciones | `/health`, `/docs`, `/openapi.json`, `/redoc` y los preflight `OPTIONS` |

Se aplica por **middleware**, no ruta a ruta: una ruta nueva queda protegida sin
que su autor se acuerde. La comparación es en tiempo constante.

## Rutas

| Método | Ruta | Entrada | Salida |
|---|---|---|---|
| `GET` | `/health` | `session_id?` | estado, `capabilities`, `limits`, `sessions` |
| `GET` | `/api/config` | — | configuración efectiva y disponibilidad de cada motor |
| `POST` | `/api/config` | parche de configuración | configuración aplicada y qué se reinició |
| `POST` | `/api/player-name` | `{track_id, name}` | `{ok: true}` |
| `POST` | `/api/player-team` | `{track_id, team}` | `{ok: true}` |
| `GET`/`POST`/`DELETE` | `/api/calibrate` | 4 puntos imagen + 4 mundo | homografía activa |
| `GET` | `/api/report` | — | informe de `build_report` |
| `GET` | `/api/export` | `include_positions?` | informe, con posiciones crudas |
| `POST` | `/api/reset` | `soft?` | estado reiniciado |
| `POST` | `/api/preview-frame` | imagen | primer frame analizado |
| `POST` | `/api/process-video` | vídeo | **stream NDJSON**, ver abajo |
| `GET` | `/api/sessions` | — | lista de sesiones vivas |
| `DELETE` | `/api/sessions/{id}` | `purge_state?` | `{ok: true}` |
| `WS` | `/ws/stream` | frames JPEG binarios | un JSON por frame |

## El protocolo de `/api/process-video`

`Content-Type: application/x-ndjson`. **Una línea JSON por frame analizado**,
según se produce. No hay envoltorio, no hay array, no hay línea final de
resumen: el stream termina cuando se cierra la conexión.

Cada línea de éxito es la respuesta de `process_frame` de `PERCEPCION` más un
campo:

```json
{"frame": 12, "t": 1.44, "video_time": 1.44, "fps": 8.3,
 "players": [...], "ball": {...}, "stats": {...}, "timings_ms": {...},
 "possession": {...}}
```

`video_time` son segundos del vídeo original y es lo que el cliente usa para
sincronizar la reproducción. `fps` son frames de **procesado** por segundo —lo
rápido que va la máquina— y no sirve para ninguna métrica.

**La línea de error puede aparecer en cualquier posición del stream**, incluida
la primera, y significa que el análisis se abortó:

```json
{"error": "No se pudo abrir el video"}
```

Esto es lo que antes no estaba escrito en ningún sitio y el cliente manejaba por
costumbre. Quien consuma el stream **debe** comprobar `"error" in linea` en cada
línea, no sólo al principio: un vídeo puede fallar a la mitad de la decodificación
y un detector puede dejar de estar disponible en mitad del análisis.

Errores conocidos que llegan por esta vía: `"No se pudo abrir el video"`,
el mensaje de `DetectorUnavailable`, y `"Fallo durante el analisis del video"`
para cualquier fallo inesperado de decodificación.

## Errores

| Situación | Código | Qué debe hacer quien llama |
|---|---|---|
| `session_id` con formato inválido | 400 | Corregir el identificador; no reintentar igual |
| Configuración fuera de rango o clave desconocida | 400 | Mostrar el mensaje: dice la clave y el rango |
| Calibración degenerada (4 puntos colineales) | 400 | Pedir cuatro puntos que formen un cuadrilátero |
| Modelo fuera de `MODEL_ROOT`, inexistente o que no es `.pt` | 400 | No reintentar: es una ruta prohibida a propósito |
| Credencial ausente o inválida (con `API_KEY`) | 401 | Pedir la credencial; no reintentar sin ella |
| Fichero que no es vídeo | 415 | Cambiar de fichero |
| Otra tarea ocupa **esta** sesión | 409 | Esperar a que termine, o usar otra sesión |
| Fichero mayor que `MAX_UPLOAD_MB` | 413 | Recortar el vídeo. El límite viaja en `/health` |
| No hay hueco para otra sesión | 429 | Reintentar más tarde o borrar sesiones viejas |
| **El servicio ya analiza `MAX_CONCURRENT_ANALYSES` vídeos** | 429 | Reintentar en unos minutos. Es un límite global, no de la sesión |
| `ultralytics` no instalado | 503 | Instalar dependencias; el mensaje dice el comando |

Los 429 son los dos únicos códigos que merecen reintento automático, y con
espera.

## Persistencia de la sesión

El estado se guarda comprimido y de forma atómica en `SESSION_STATE_DIR`, y se
restaura al arrancar. Sobrevive a un reinicio del backend. Caduca por
`SESSION_TTL_SECONDS` y hay un tope de `MAX_SESSIONS` vivas; al superarlo se
desaloja la menos usada.

**Si cambias `serialize_state`/`load_state`, versiona el formato**: sin versión,
una actualización rompe las sesiones guardadas de quien ya tenía un partido a
medias.

## Variables de entorno

| Variable | Por defecto | Qué hace |
|---|---|---|
| `API_KEY` | *(vacía)* | Credencial. Vacía = servicio abierto |
| `CORS_ALLOW_ORIGINS` | `*` | Orígenes admitidos, separados por comas |
| `MAX_UPLOAD_MB` | `1024` | Tamaño máximo por subida |
| `MAX_CONCURRENT_ANALYSES` | `WORKER_THREADS` | Análisis de vídeo simultáneos en todo el servicio |
| `WORKER_THREADS` | `2` | Hilos para el trabajo pesado |
| `MAX_SESSIONS` | `12` | Sesiones vivas |
| `SESSION_TTL_SECONDS` | `1800` | Caducidad por inactividad |
| `SESSION_STATE_DIR` | `.session_state` | Dónde se guardan las sesiones |
| `MODEL_ROOT` | `.` | Raíz bajo la que pueden vivir los pesos |
| `LOG_LEVEL` | `INFO` | Nivel de registro |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Escucha |

`OPERACION` depende de esta tabla.

## Qué NO expone

- **No hay identidad de usuario.** `session_id` no es autenticación ni con
  `API_KEY` puesta: la credencial dice *quién puede entrar*, no *qué sesión es
  suya*. Dos clientes con la misma credencial se ven las sesiones entre sí.
- **No hay límite por cliente**, sólo globales y por sesión. No se puede impedir
  que alguien abra sesiones nuevas sin parar.
- **`/api/sessions` enumera todas las sesiones vivas.** Con el servicio abierto,
  es un directorio de identificadores ajenos.
- **El orden de las líneas del stream es el de análisis**, no está garantizado
  que `frame` sea consecutivo: con `frame_skip` hay huecos.
- **No hay reanudación.** Si el stream se corta, se vuelve a subir el vídeo
  entero; el estado parcial de la sesión se conserva pero el análisis no se
  retoma donde iba.
- **`/health` responde sin credencial a propósito** y revela versión,
  capacidades y número de sesiones vivas.

## Quién depende de esto

| Carril | Qué usa |
|---|---|
| `CLIENTE` | Todas las rutas y el protocolo NDJSON; el contrato de `session_id` |
| `OPERACION` | La tabla de variables de entorno, los puertos y los límites |

## Cambios desde la versión anterior

Primera publicación. Respecto del código previo:

- **Añade:** `API_KEY` (apagada por defecto), `MAX_CONCURRENT_ANALYSES`,
  `limits` en `/health`, y un aviso al arrancar sin autenticación.
- **Corrige:** el WebSocket pasaba el reloj de pared como si fuera tiempo de
  vídeo, así que las métricas de webcam se etiquetaban como comparables con las
  de un fichero. Ahora declara su base de tiempo como `reloj`.
- **Añade:** `DELETE /api/calibrate` y `GET /api/report` (venían de la PR #1).
