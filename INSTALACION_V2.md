# ⚡ Football Copilot v2 — Instalación y Arranque

**Sistema:** macOS · Intel i7 · 16 GB · Sin GPU

---

## 1. Requisitos previos

```bash
# Verificar versiones
python3 --version   # ≥ 3.10
node --version      # ≥ 18
npm --version       # ≥ 9
```

Si no tienes Python 3.10+:
```bash
brew install python@3.11
```

---

## 2. Backend Python

```bash
# Crear entorno virtual (una sola vez)
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias v2
pip install --upgrade pip
pip install -r requirements_v2.txt

# Descargar modelo YOLO (primera vez, ~6MB)
python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt'); print('✅ Modelo OK')"

# Arrancar backend
python3 football_copilot_v2_backend.py
# ✅ Escuchando en http://0.0.0.0:8000
# ✅ Swagger en  http://localhost:8000/docs
```

---

## 3. Frontend React

```bash
# En otra terminal, en el mismo directorio
npm install
npm start
# ✅ Abre automáticamente http://localhost:3000
```

> Si el proyecto ya tiene `FootballCopilot.jsx`, reemplaza las referencias en
> `App.jsx` con `FootballCopilot_v2.jsx`:
> ```jsx
> import FootballCopilotV2 from './FootballCopilot_v2';
> // ...
> <FootballCopilotV2 />
> ```

---

## 4. Usar el sistema

### Opción A — Video grabado (recomendado para empezar)

1. Abre http://localhost:3000
2. Selecciona **📁 Video**
3. Elige tu `.mp4` del dron o cámara lateral
4. El backend procesa y transmite resultados frame a frame

### Opción B — Cámara en vivo / Drone

1. Selecciona **📷 Cámara**
2. El navegador pedirá permiso de cámara → Aceptar
3. Clic en **🔴 Iniciar Cámara**
4. Los frames se envían por WebSocket al backend

Para drones DJI via OBS:
- OBS → Configurar RTMP output → `rtmp://localhost:1935/live/stream`
- En backend, conectar `cv2.VideoCapture("rtmp://localhost:1935/live/stream")`

---

## 5. Calibración de velocidad

La velocidad se calcula en píxeles/metro. Para calibrarlo con tu cancha:

1. En el video, mide cuántos píxeles equivalen a 10 metros reales
2. Llama al endpoint:
```bash
curl -X POST http://localhost:8000/api/calibrate \
     -H "Content-Type: application/json" \
     -d '{"pixels_per_meter": 12.5}'
```

Valor típico para toma aérea de drone: **8–15 px/m** (varía con altura).

---

## 6. Flujo del sistema v2

```
[Video .mp4 / Webcam / Drone RTMP]
          │
          ▼
  [FastAPI Backend v2]
  │  YOLOv8n → personas (clase 0) + balón (clase 32)
  │  ByteTrack (supervision) → IDs persistentes
  │  KMeans clustering → Equipo 1 🟢 / Equipo 2 🔴
  │  Speed calculator → km/h por jugador
  │  Possession tracker → % por equipo
          │  JSON ~12-20 FPS
          ▼
  [React Frontend v2]
  │  Canvas 2D: círculos verde/rojo, nombre, velocidad
  │  Trail: últimas 20 posiciones con fade
  │  Heatmap: densidad de posiciones
  │  Panel: stats, posesión, lista editable
  │  Botón Export → .json con partido completo
```

---

## 7. Endpoints disponibles

| Método | URL | Descripción |
|---|---|---|
| `GET`  | `/health` | Estado del servidor + FPS |
| `POST` | `/api/process-video` | Subir video (multipart) → NDJSON stream |
| `WS`   | `/ws/stream` | WebSocket frames JPEG → JSON detecciones |
| `POST` | `/api/player-name` | `{track_id, name}` — editar nombre |
| `POST` | `/api/calibrate` | `{pixels_per_meter}` — calibrar velocidad |
| `GET`  | `/api/export` | Exportar partido completo como JSON |
| `POST` | `/api/reset` | Reiniciar tracker y estadísticas |
| `GET`  | `/docs` | Swagger UI interactivo |

---

## 8. Optimización para i7 2018

Si el FPS es bajo, prueba en orden:

```python
# En football_copilot_v2_backend.py

# 1. Reducir tamaño de entrada YOLO (línea YOLO_IMGSZ)
YOLO_IMGSZ = 416        # en vez de 640 → ~40% más rápido

# 2. Reducir resolución del video antes de procesar
frame = cv2.resize(frame, (640, 360))

# 3. Procesar 1 de cada 2 frames
# En /api/process-video, cambiar:
frame_skip = 1          # procesa frame 1, salta frame 2
```

Rendimiento esperado en i7 16GB:

| Resolución | imgsz | FPS estimado |
|---|---|---|
| 854×480    | 640   | ~8-12 FPS    |
| 640×360    | 416   | ~15-20 FPS   |
| 640×360    | 320   | ~25-30 FPS   |

---

## 9. Clasificador KMeans — Cómo funciona

El clasificador se entrena **automáticamente** en los primeros frames cuando detecta
≥6 jugadores. Agrupa los colores de camiseta en 2 clusters (Equipo 1 y 2).

- No necesitas configurar colores manualmente
- Funciona con cualquier color de kit
- Si los equipos tienen camisetas muy similares, se puede re-entrenar con `POST /api/reset`

---

**Football Copilot v2 · Maestre · Abril 2026**
