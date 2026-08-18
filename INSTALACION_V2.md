# ⚡ Football Copilot — Instalación y arranque

**Referencia de rendimiento:** MacBook Pro 2018 · Intel i7 · 16 GB · sin GPU.
Funciona igual en Linux; en Windows usa `venv\Scripts\activate`.

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
