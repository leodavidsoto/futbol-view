# ⚽ Football Copilot

Análisis de partidos de fútbol a partir de vídeo: detección de jugadores y
balón, seguimiento con identidades persistentes, clasificación automática de
equipos y métricas de rendimiento (distancia, velocidad, sprints, posesión).

```
[vídeo .mp4 / cámara]
        │
        ▼
 fcopilot.detection      YOLO (+ SAHI para tomas aéreas)
        │
        ▼
 tracker                 Norfair · ByteTrack · centroides (respaldo)
        │
        ▼
 fcopilot.teams          KMeans de color de camiseta (filtrando césped) u OSNet
        │
        ▼
 fcopilot.kinematics     distancia, velocidad, sprints, zonas de intensidad
 fcopilot.possession     posesión con histéresis, en segundos reales
        │
        ▼
 FastAPI  →  NDJSON / WebSocket  →  React (canvas + panel)
```

## Estructura

| Ruta | Qué es |
|---|---|
| `fcopilot/` | Núcleo de análisis. Sin FastAPI y sin dependencias pesadas obligatorias. |
| `football_copilot_v2_backend.py` | Capa HTTP/WebSocket: valida, resuelve sesión y delega. |
| `frontend/` | Interfaz Vite + React (`src/App.jsx` y utilidades en `src/lib/`). |
| `tests/` | Suite de pytest del backend y del núcleo. |
| `frontend/src/lib/__tests__/` | Suite de vitest del frontend. |

Dentro de `fcopilot/`:

| Módulo | Responsabilidad |
|---|---|
| `config.py` | Configuración del runtime y su validación (rangos, enums). |
| `detection.py` | YOLO y SAHI, ambos opcionales, con registro de modelos compartido. |
| `tracking.py` | Tracker de centroides de respaldo, sin dependencias. |
| `teams.py` | Clasificación de equipos por color, con voto temporal por track. |
| `osnet.py` | Re-identificación por apariencia (requiere PyTorch). |
| `kinematics.py` | Distancia, velocidad, sprints y zonas de esfuerzo por jugador. |
| `possession.py` | Posesión de balón con histéresis y contabilidad en segundos. |
| `geometry.py` | Homografía imagen→campo en numpy puro. |
| `report.py` | Informe agregado del partido. |
| `analyzer.py` | Orquestador con estado: une todo lo anterior. |
| `sessions.py` | Sesiones aisladas con TTL, límite y persistencia en disco. |

## Arranque rápido

```bash
# Backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements_v2.txt
python football_copilot_v2_backend.py        # http://localhost:8000/docs

# Frontend (en otra terminal)
cd frontend && npm install && npm run dev     # http://localhost:5173
```

Detalles de instalación y ajuste de rendimiento: [`INSTALACION_V2.md`](INSTALACION_V2.md).
Flujo de uso paso a paso: [`QUICK_START.md`](QUICK_START.md).

## Sesiones

Cada pestaña del navegador genera su propio `session_id` y lo envía en la
cabecera `x-session-id` (o en el query string del WebSocket). El backend
mantiene un analizador independiente por sesión, lo persiste comprimido en
`SESSION_STATE_DIR` y lo caduca tras `SESSION_TTL_SECONDS` de inactividad. Dos
personas pueden analizar partidos distintos contra el mismo servidor sin
pisarse.

## API

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Estado, capacidades disponibles y resumen de sesiones. |
| `GET` | `/api/sessions` | Sesiones vivas y estadísticas del gestor. |
| `DELETE` | `/api/sessions/{id}` | Elimina una sesión (y opcionalmente su estado). |
| `GET`/`POST` | `/api/config` | Lee y modifica el runtime (modelo, tracker, umbrales…). |
| `POST` | `/api/player-name` | Renombra un track. |
| `POST` | `/api/player-team` | Fuerza el equipo de un track. |
| `GET`/`POST`/`DELETE` | `/api/calibrate` | Escala px/m u homografía de 4 puntos. |
| `POST` | `/api/preview-frame` | Detecta en un frame suelto antes de analizar. |
| `POST` | `/api/process-video` | Sube un vídeo y devuelve NDJSON en streaming. |
| `WS` | `/ws/stream` | Frames JPEG en vivo → detecciones. |
| `GET` | `/api/export` | Informe completo del partido (con posiciones). |
| `GET` | `/api/report` | Mismo informe sin el rastro de posiciones. |
| `POST` | `/api/reset` | Reinicio completo, o `?soft=true` conservando asignaciones. |

## Variables de entorno

| Variable | Por defecto | Para qué |
|---|---|---|
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Dirección de escucha. |
| `CORS_ALLOW_ORIGINS` | `*` | Orígenes permitidos, separados por comas. |
| `MAX_UPLOAD_MB` | `1024` | Tamaño máximo de subida. |
| `MAX_SESSIONS` | `12` | Sesiones simultáneas en memoria. |
| `SESSION_TTL_SECONDS` | `1800` | Inactividad antes de caducar una sesión. |
| `SESSION_STATE_DIR` | `.session_state` | Dónde se persiste el estado. |
| `MODEL_ROOT` | `.` | Raíz permitida para los pesos `.pt`. |
| `WORKER_THREADS` | `2` | Hilos para la inferencia fuera del event loop. |
| `LOG_LEVEL` | `INFO` | Nivel de log. |

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                   # núcleo + API
cd frontend && npm test                  # utilidades del frontend
```

La suite no descarga pesos ni ejecuta una red neuronal: inyecta un detector
guionizado, así que corre en segundos. Ver [`TESTING.md`](TESTING.md).

## Dependencias opcionales

`ultralytics`, `sahi`, `norfair`, `supervision` y `torch` son opcionales: si
falta alguna, el backend arranca igual, lo indica en `/health` y degrada al
mejor sustituto disponible (por ejemplo, del tracker de Norfair al de
centroides). Sólo la detección necesita `ultralytics` de verdad; sin él,
los endpoints de análisis responden `503` con un mensaje explícito.
