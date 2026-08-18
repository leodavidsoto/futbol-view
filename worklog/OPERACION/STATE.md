# OPERACION — estado

| | |
|---|---|
| **Estado** | EN_CURSO |
| **Último agente** | claude (turno 1 de OPERACION) |
| **Última actualización** | 2026-08-19T00:25:00Z |
| **Contrato publicado** | sí — `worklog/OPERACION/CONTRATO.md` v1 |
| **Depende de** | `API` v1 (**publicado**); `PLATAFORMA` para cerrar |
| **Requisitos asignados** | R-26, R-29, R-30 |

## Qué está hecho

- `INSTALACION_V2.md` y `QUICK_START.md` corregidos: antes mandaban `npm start`
  en el puerto 3000 y editar un `.jsx` de la raíz que no forma parte de la
  aplicación. Ahora describen Vite en el 5173 y `frontend/src/App.jsx`.
- `requirements_v2.txt` separado de `requirements-dev.txt`, que es lo que permite
  que CI instale 80 MB en vez de varios gigabytes.

Y en este turno:

- **Imagen y despliegue**: `Dockerfile` con targets `servicio` y `web`,
  `docker-compose.yml`, `.dockerignore` y `deploy/nginx.conf` con las tres cosas
  que rompen un streaming NDJSON detrás de un proxy (`proxy_buffering off`,
  timeouts largos, `client_max_body_size` a la altura de `MAX_UPLOAD_MB`).
- **Provisión de pesos** (R-26, R-29): `scripts/fetch_weights.py` descarga de
  forma atómica y **verifica SHA-256**. Un `.pt` es un pickle y cargarlo ejecuta
  código: `MODEL_ROOT` dice dónde está el fichero, el hash dice qué contiene.
- **Retención** (R-30): `scripts/purge_sessions.py`, con perfil de compose para
  correrlo cada hora. Por defecto 7 días.
- **Documentación**: `INSTALACION_V2.md` gana la vía de contenedores, la sección
  de pesos, la tabla de variables de entorno, la de retención y un **runbook**
  de once síntomas con su causa.
- 23 pruebas en `tests/test_scripts.py`.

## Qué falta — **el carril NO cierra**

El criterio de cierre es «desde un clon limpio, un comando levanta el sistema y
analiza un vídeo de prueba de extremo a extremo». Falta:

1. **Construir la imagen.** En este entorno **no hay demonio de Docker**, así que
   el `Dockerfile` y el `compose` están escritos y revisados pero **nadie los ha
   ejecutado**. Es lo primero que tiene que hacer quien retome, y hasta entonces
   no se puede decir que funcionen.
2. **Rellenar los hashes reales** de `weights.sha256.json`. Hoy son `TODO(config)`:
   nadie puede fijar un hash que no ha calculado, y la regla 2 prohíbe inventarlo.
3. **El vídeo de prueba.** No hay ninguno en el repositorio, así que el recorrido
   de extremo a extremo no se puede automatizar. Sin él, el criterio de cierre se
   verifica a mano.

## Bloqueos activos

- **A-02 sin responder.** La retención de 7 días es provisional y está elegida
  corta a propósito: ampliarla luego no cuesta nada, y haber guardado de más no
  se puede deshacer.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | `requirements_v2.txt` es de este carril y `requirements-dev.txt` de `PLATAFORMA` | Uno describe producción y el otro CI; cambian por razones distintas | sí | Unificarlos y perder la propiedad de que CI corra ligero |
| 2 | Los pesos se montan como volumen, no se hornean en la imagen | Cientos de megas que cambian de versión no deben quedar congelados en una capa, y obligarían a reconstruir la imagen para actualizarlos | sí | Hornearlos si alguna vez importa más la reproducibilidad exacta que el tamaño |
| 3 | nginx delante en vez de que la API sirva los estáticos | `football_copilot_v2_backend.py` es de `API`: montarlos desde aquí sería tocar un carril ajeno. Y con nginx delante, cliente y API comparten origen y CORS puede cerrarse | sí | Que `API` monte los estáticos; hay solicitud abierta |
| 4 | Retención por defecto de 7 días con A-02 abierta | Corto a propósito: ampliar luego es gratis, haber guardado de más no se deshace | sí | Responder A-02 |
| 5 | `weights.sha256.json` se entrega con `TODO(config)` | Regla 2: no se inventa un hash que no se ha calculado | sí | Ejecutar `--print-hashes` tras la primera descarga |
| 6 | La API no publica puertos en el compose | Sólo se llega por nginx, que es lo que mantiene el mismo origen | sí | Añadir `8000:8000` para depurar |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| ~~`API`~~ | ~~Tabla de variables de entorno~~ — resuelta en su contrato v1 | 2026-08-18 |
| `API` | Que monte los estáticos del cliente (`app.mount("/", StaticFiles(...))`), para poder desplegar en un solo contenedor. Mientras tanto va nginx delante, que tampoco está mal | 2026-08-19 |
| ~~`PLATAFORMA`~~ | ~~Este carril no tenía ninguna ruta de tests asignada~~ — resuelto: `tests/test_scripts.py` | 2026-08-19 |

## Notas para quien retome

- **La regla 7 al escribir la imagen:** producción sí lleva las dependencias
  pesadas, CI no puede llevarlas. Son dos ficheros de requisitos distintos y
  tienen que seguir siéndolo; unificarlos rompe la propiedad que hace que la
  suite corra en segundos.
- El criterio de cierre —clon limpio, un comando, vídeo de prueba de extremo a
  extremo— **hoy es imposible** por los pesos. Ese es el trabajo, no un detalle.
- No hay ningún vídeo de prueba en el repositorio, ni un partido etiquetado a
  mano. Sin eso, ninguna prueba dice si las métricas se parecen a la realidad
  (ver `ANALISIS.md` §0.7). Conseguirlo es trabajo de campo y no lo cubre ningún
  carril.
- **Las tres líneas de `deploy/nginx.conf` que parecen de relleno no lo son.**
  `proxy_buffering off` es lo único que hace que el NDJSON llegue frame a frame:
  con el buffer puesto, el cliente no recibe nada hasta que termina el análisis y
  la barra de progreso se queda quieta. `proxy_read_timeout 3600s` evita el corte
  a los 60 segundos por defecto. Y `client_max_body_size` tiene que subir **a la
  vez** que `MAX_UPLOAD_MB`, o nginx devuelve un 413 propio antes de que la API
  vea la petición, con un mensaje que no dice de dónde viene.
- Al escribir el `Dockerfile` descubrí que el backend **no monta estáticos**. Lo
  correcto habría sido que lo hiciera él, pero ese fichero es de `API`: quedó
  como solicitud y de momento va nginx delante, que además cierra el problema de
  CORS de paso.
- Este carril **no tenía ruta de tests** en el mapa original: no se podía escribir
  una prueba sin salirse del carril. Es un defecto del corte, no del guardia; lo
  arregló `PLATAFORMA` añadiendo `tests/test_scripts.py`.
