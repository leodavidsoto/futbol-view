# ⚡ Football Copilot — Instalación y arranque

**Referencia de rendimiento:** MacBook Pro 2018 · Intel i7 · 16 GB · sin GPU.
Funciona igual en Linux; en Windows usa `venv\Scripts\activate`.

---

## 0. La vía rápida: contenedores

Si sólo quieres que funcione, esto levanta el sistema entero sin instalar Python
ni Node en tu máquina:

```bash
python3 scripts/fetch_weights.py --dest ./weights   # una sola vez
docker compose up --build
```

Cliente en **http://localhost:8080**. La API va detrás del mismo origen, así que
no hay que tocar CORS.

Los pesos **no van dentro de la imagen**: pesan cientos de megas, cambian de
versión y no deben quedar congelados en una capa. Se montan como volumen de sólo
lectura desde `./weights`.

El resto del documento es la instalación manual, que sigue siendo la cómoda para
desarrollar.

---

## 1. Requisitos previos

```bash
python3 --version   # ≥ 3.10
node --version      # ≥ 18
npm --version       # ≥ 9
```

Si no tienes Python 3.10+ en macOS: `brew install python@3.11`.

---

## 2. Backend

```bash
python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
# PyTorch primero, en su rueda de CPU (opcional: sólo hace falta para OSNet)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements_v2.txt

# Descargar el modelo YOLO (primera vez)
python3 -c "from ultralytics import YOLO; YOLO('yolo11x.pt'); print('✅ Modelo OK')"

python3 football_copilot_v2_backend.py
# ✅ http://0.0.0.0:8000  ·  Swagger en http://localhost:8000/docs
```

Comprueba qué se ha detectado en tu entorno:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

El bloque `capabilities` indica qué hay instalado (`yolo`, `sahi`, `norfair`,
`bytetrack`, `torch`, `osnet`). Lo que falte se degrada solo: sin Norfair se usa
ByteTrack, y sin ninguno de los dos, el tracker de centroides incluido. Sólo
`ultralytics` es imprescindible para detectar: sin él los endpoints de análisis
responden `503` con el motivo.

---

## 3. Frontend

```bash
cd frontend
npm install
npm run dev
# ✅ http://localhost:5173
```

Si el backend no está en `localhost:8000`, crea `frontend/.env`:

```bash
VITE_API_URL=http://mi-servidor:8000
VITE_WS_URL=ws://mi-servidor:8000
```

> La interfaz activa es `frontend/src/App.jsx`. El fichero `FootballCopilot_v2.jsx`
> de la raíz es una versión anterior que se conserva como referencia histórica y
> no forma parte de la aplicación.

---

## 4. Usar el sistema

### Opción A — Vídeo grabado (recomendado)

1. Abre http://localhost:5173
2. Selecciona **📁 Video** y elige tu `.mp4`.
3. Navega al segundo que quieras y pulsa **🔍 Detectar aquí**.
4. Corrige equipos y nombres haciendo clic en los círculos.
5. **▶ Iniciar análisis**: el backend devuelve NDJSON frame a frame.

### Opción B — Cámara en vivo / dron

1. Selecciona **📷 Cámara** y acepta el permiso del navegador.
2. Los frames viajan por WebSocket (`/ws/stream`) con el `session_id` de la pestaña.

Para drones DJI vía OBS: envía RTMP a `rtmp://localhost:1935/live/stream` y abre
esa URL con `cv2.VideoCapture` en el backend.

---

## 5. Calibración del campo

**Recomendado:** homografía de 4 puntos desde la interfaz
(**🏟️ Calibrar campo**). Marca las esquinas en orden — superior izquierda,
superior derecha, inferior derecha, inferior izquierda — y las posiciones pasan
a medirse en metros reales.

```bash
# Equivalente por API
curl -X POST http://localhost:8000/api/calibrate \
     -H "Content-Type: application/json" \
     -H "x-session-id: mi-sesion" \
     -d '{"img_points": [[120,90],[740,90],[810,430],[50,430]],
          "world_points": [[0,0],[105,0],[105,68],[0,68]]}'
```

Alternativa simple, sin corregir la perspectiva:

```bash
curl -X POST http://localhost:8000/api/calibrate \
     -H "Content-Type: application/json" \
     -d '{"pixels_per_meter": 12.5}'
```

Valor típico en tomas aéreas: **8–15 px/m**. Ten en cuenta que una escala fija
sobreestima las distancias en el fondo del plano y las infravalora en primer
plano; la homografía no tiene ese problema.

---

## 6. Endpoints

Ver la tabla completa en el [`README.md`](README.md) o en `/docs`.

Todas las rutas aceptan la cabecera `x-session-id` (o `?session_id=`) para
trabajar sobre una sesión concreta. Sin ella se usa `default`.

---

## 7. Ajuste de rendimiento en CPU

Todo se cambia en caliente, sin reiniciar, desde el panel **⚙️ Config** o por API:

```bash
curl -X POST http://localhost:8000/api/config \
     -H "Content-Type: application/json" \
     -d '{"imgsz": 640, "detection_mode": "normal", "frame_skip": 3}'
```

| Ajuste | Efecto |
|---|---|
| `imgsz` 1280 → 640 | El mayor ahorro; pierde detecciones lejanas. |
| `detection_mode: "normal"` | Desactiva SAHI (los tiles multiplican el coste). |
| `frame_skip` | Analiza 1 de cada `frame_skip + 1` frames. |
| `augment: false` | El TTA duplica el tiempo por frame. |
| `model` | `yolo11n.pt` es varias veces más rápido que `yolo11x.pt`. |

`frame_skip` ya **no** distorsiona las métricas: velocidades y distancias se
calculan sobre el tiempo real del vídeo, no sobre el número de frames vistos.

Rendimiento orientativo en un i7 de 2018 (854×480):

| imgsz | Modo | FPS aproximados |
|---|---|---|
| 1280 | SAHI | 1–3 |
| 640 | normal | 8–12 |
| 416 | normal | 15–20 |

---

## 8. Clasificación de equipos

Tres modos, seleccionables en el panel **🧠 Modelos**:

- `grass_kmeans` *(por defecto)* — KMeans sobre el color de camiseta filtrando
  el césped. Se entrena solo con muestras de varios frames.
- `kmeans` — la variante simple, sin filtrar el verde.
- `osnet` — embeddings de apariencia (requiere PyTorch y los pesos en
  `weights/`); útil cuando los dos kits tienen colores parecidos.

Las etiquetas son estables: `team_1` sigue siendo `team_1` aunque el
clasificador se reajuste, y cada track conserva su equipo por voto de sus
últimas observaciones, así que no parpadea al cruzarse dos jugadores.

Si aun así se equivoca, haz clic en el jugador y asígnale el equipo a mano: la
asignación manual tiene prioridad y sobrevive a `POST /api/reset?soft=true`.

---

## 9. Desarrollo

```bash
pip install -r requirements-dev.txt && pytest
cd frontend && npm run lint && npm test && npm run build
```

Ver [`TESTING.md`](TESTING.md).


---

## 9. Pesos del modelo

Nada funciona sin ellos y hasta ahora nadie los provisionaba: se daban por
presentes, y en un clon limpio el análisis fallaba con un error de `ultralytics`
que no decía que faltara un fichero.

```bash
python3 scripts/fetch_weights.py --dest ./weights     # descarga y verifica
python3 scripts/fetch_weights.py --dest ./weights --check-only
python3 scripts/fetch_weights.py --dest ./weights --print-hashes
```

Luego arranca el backend con `MODEL_ROOT=./weights`.

**Por qué se verifica el hash y no basta con descargar:** un `.pt` es un pickle
de PyTorch, y cargarlo **ejecuta código**. `MODEL_ROOT` restringe *dónde* puede
estar el fichero; el hash es lo único que dice *qué* contiene.

La primera vez, `scripts/weights.sha256.json` trae `TODO(config)` en lugar de los
hashes: nadie puede fijar un hash que no ha calculado. Descarga de una fuente en
la que confíes, ejecuta `--print-hashes` y pega el resultado. A partir de ahí,
cualquier cambio del fichero se detecta.

**OSNet** (`osnet_x1_0_imagenet.pth`) no tiene una URL de descarga pública y
estable que podamos fijar, así que el script no lo descarga: colócalo a mano y
añade su hash. Sin él, el clasificador de equipos degrada a `grass_kmeans`, que
es el valor por defecto de todas formas.

---

## 10. Variables de entorno

La tabla completa está en `worklog/API/CONTRATO.md`. Las que importan al
desplegar:

| Variable | Por defecto | Cuándo cambiarla |
|---|---|---|
| `API_KEY` | *(vacía)* | **Siempre antes de exponer esto fuera de tu máquina.** Vacía = servicio abierto |
| `CORS_ALLOW_ORIGINS` | `*` | Igual: con nginx delante, cliente y API comparten origen y puedes cerrarlo |
| `MODEL_ROOT` | `.` | Debe apuntar al directorio de pesos |
| `MAX_UPLOAD_MB` | `1024` | Si tus vídeos son más pequeños, bájalo: es superficie de ataque gratis |
| `MAX_CONCURRENT_ANALYSES` | `WORKER_THREADS` | Análisis simultáneos en todo el servicio |
| `SESSION_STATE_DIR` | `.session_state` | Debe ser un volumen persistente |

Al arrancar sin `API_KEY`, el backend registra un aviso diciendo exactamente
esto. No es decorativo: sin credencial, cualquiera que conozca o adivine un
`session_id` lee el partido de otro.

---

## 11. Retención de datos

El vídeo subido **se borra al terminar el análisis** y no se guarda nunca. Lo que
sí persiste son los datos derivados —nombres, equipos, calibración,
trayectorias— en `SESSION_STATE_DIR`, y crecen sin límite.

```bash
python3 scripts/purge_sessions.py --dir .session_state --max-age-days 7
python3 scripts/purge_sessions.py --dir .session_state --dry-run
docker compose --profile mantenimiento up -d purga     # cada hora, desatendido
```

La retención por defecto son 7 días y es **provisional**: la decisión de cuánto
tiempo se pueden conservar estos datos sigue abierta (A-02 en `ANALISIS.md`).
Siete días es corto a propósito — ampliarlo luego no cuesta nada, y haber
guardado de más no se puede deshacer.

---

## 12. Runbook: qué hacer cuando se rompe

| Síntoma | Causa casi siempre | Qué hacer |
|---|---|---|
| El análisis falla al instante y el log dice `DetectorUnavailable` | Faltan los pesos, o `ultralytics` no está instalado | `scripts/fetch_weights.py --check-only`; el mensaje del error trae el comando de instalación |
| `El modelo debe estar dentro del proyecto` (400) | La ruta del modelo cae fuera de `MODEL_ROOT` | Es deliberado. Mueve el fichero o ajusta `MODEL_ROOT` |
| 401 en todas las peticiones | El backend tiene `API_KEY` y el cliente no | Reconstruye el cliente con `VITE_API_KEY`, o quita la credencial |
| 429 «el servicio ya está analizando N vídeos» | Límite global alcanzado | Esperar. Subir `MAX_CONCURRENT_ANALYSES` sólo ayuda si también subes `WORKER_THREADS` |
| 429 «no hay hueco para otra sesión» | `MAX_SESSIONS` alcanzado | Borrar sesiones viejas con `DELETE /api/sessions/{id}` |
| 413 al subir | El vídeo supera `MAX_UPLOAD_MB`, o el `client_max_body_size` de nginx | Los dos límites tienen que subir a la vez |
| La barra de progreso no se mueve pero el análisis avanza | Algún proxy está almacenando el NDJSON | `proxy_buffering off`, ya puesto en `deploy/nginx.conf` |
| Se corta a los 60 segundos | Timeout del proxy | `proxy_read_timeout`, ya puesto en `deploy/nginx.conf` |
| `import cv2` falla en el contenedor | Faltan `libgl1`/`libglib2.0-0` | Ya están en el `Dockerfile`; si construyes otra imagen, acuérdate |
| Las velocidades parecen multiplicadas | Base de tiempo equivocada | Mira `meta.time_source` del informe: si dice `reloj`, son métricas de webcam y no son comparables con las de un fichero |
| El disco se llena | `SESSION_STATE_DIR` sin purgar | Sección 11 |
