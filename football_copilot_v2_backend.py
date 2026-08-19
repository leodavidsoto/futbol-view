"""
Football Copilot — Backend HTTP/WebSocket.

Capa fina sobre el paquete :mod:`fcopilot`: valida las peticiones, resuelve la
sesión y delega el análisis. Toda la lógica de visión y de métricas vive en
``fcopilot/`` para que pueda probarse sin levantar el servidor.

Arranque:
    python football_copilot_v2_backend.py
    uvicorn football_copilot_v2_backend:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:  # OpenCV es obligatorio en producción; sin él sólo funcionan los tests puros.
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

from fcopilot import __version__ as FCOPILOT_VERSION
from fcopilot.analyzer import BYTETRACK_AVAILABLE, NORFAIR_AVAILABLE, FootballAnalyzer
from fcopilot.config import ALLOWED_MANUAL_TEAMS, ConfigError, DEFAULTS, validate_config
from fcopilot.detection import SAHI_AVAILABLE, YOLO_AVAILABLE, DetectorUnavailable, shared_yolo_registry
from fcopilot.geometry import CalibrationError
from fcopilot.osnet import TORCH_AVAILABLE, osnet_weights_available, shared_osnet_registry
from fcopilot.sessions import SessionIdError, SessionLimitError, SessionManager, normalize_session_id

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN DEL SERVICIO (variables de entorno)
# ─────────────────────────────────────────────────────────────
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1024"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "12"))
SESSION_STATE_DIR = Path(os.getenv("SESSION_STATE_DIR", ".session_state"))
MODEL_ROOT = Path(os.getenv("MODEL_ROOT", ".")).resolve()
WORKER_THREADS = int(os.getenv("WORKER_THREADS", "2"))
#: Credencial opcional. Vacía = servicio abierto, que sólo es aceptable en local.
#: Ver la ambigüedad A-01 de ANALISIS.md: mientras no se responda si esto se
#: expone, la autenticación existe pero viene apagada para no romper el uso local.
API_KEY = os.getenv("API_KEY", "").strip()
#: Análisis de vídeo simultáneos en todo el servicio. Con WORKER_THREADS=2, más
#: de dos no van más rápido: sólo compiten por los mismos hilos y multiplican la
#: memoria y el disco temporal ocupados.
MAX_CONCURRENT_ANALYSES = int(os.getenv("MAX_CONCURRENT_ANALYSES", str(max(1, WORKER_THREADS))))
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
START_TIME = time.time()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("football_copilot")


# ─────────────────────────────────────────────────────────────
# ESQUEMAS
# ─────────────────────────────────────────────────────────────
class PlayerNameRequest(BaseModel):
    track_id: str
    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name vacio")
        return value


class PlayerTeamRequest(BaseModel):
    track_id: str
    team: str

    @field_validator("team")
    @classmethod
    def validate_team(cls, value: str) -> str:
        if value not in ALLOWED_MANUAL_TEAMS:
            raise ValueError("team invalido")
        return value


class CalibrationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pixels_per_meter: Optional[float] = Field(default=None, gt=0, le=1000)
    img_points: Optional[List[List[float]]] = None
    world_points: Optional[List[List[float]]] = None


class ConfigRequest(BaseModel):
    """Parche de configuración. Los rangos los valida ``fcopilot.config``."""

    model_config = ConfigDict(extra="forbid")
    model: Optional[str] = None
    confidence: Optional[float] = None
    imgsz: Optional[int] = None
    iou: Optional[float] = None
    agnostic_nms: Optional[bool] = None
    augment: Optional[bool] = None
    detection_mode: Optional[str] = None
    sahi_slice: Optional[int] = None
    sahi_overlap: Optional[float] = None
    tracker_type: Optional[str] = None
    norfair_dist: Optional[int] = None
    norfair_hit_max: Optional[int] = None
    team_classifier: Optional[str] = None
    frame_skip: Optional[int] = None
    # Resolución a la que se analiza. Estaban en los defaults y validados en
    # `fcopilot.config`, pero no en este esquema, así que la API los rechazaba y
    # nadie podía salir de 854x480. En tomas elevadas y anchas —donde los
    # jugadores ocupan pocos píxeles— esa reducción se come las detecciones.
    process_width: Optional[int] = None
    process_height: Optional[int] = None

    def to_patch(self) -> Dict[str, Any]:
        payload = self.model_dump(exclude_none=True)
        if "model" in payload:
            payload["model_path"] = payload.pop("model")
        return payload


# ─────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────
session_manager = SessionManager(
    state_dir=SESSION_STATE_DIR,
    ttl_seconds=SESSION_TTL_SECONDS,
    max_sessions=MAX_SESSIONS,
)
#: Plazas de análisis de vídeo simultáneo en todo el servicio.
analysis_slots = threading.BoundedSemaphore(MAX_CONCURRENT_ANALYSES)


class WorkerPool:
    """Pool compartido para el trabajo pesado, creado bajo demanda.

    Se recrea si alguien lo apagó (por ejemplo entre dos ciclos de vida de la
    app en los tests), en vez de dejar la API inservible.
    """

    def __init__(self, size: int):
        self._size = max(1, size)
        self._lock = threading.Lock()
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None

    def get(self) -> concurrent.futures.ThreadPoolExecutor:
        with self._lock:
            if self._pool is None:
                self._pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=self._size, thread_name_prefix="fcopilot"
                )
            return self._pool

    def shutdown(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.shutdown(wait=False)
                self._pool = None


workers = WorkerPool(WORKER_THREADS)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Football Copilot %s — yolo=%s sahi=%s norfair=%s bytetrack=%s torch=%s",
        FCOPILOT_VERSION, YOLO_AVAILABLE, SAHI_AVAILABLE, NORFAIR_AVAILABLE, BYTETRACK_AVAILABLE, TORCH_AVAILABLE,
    )
    if not API_KEY:
        logger.warning(
            "SERVICIO SIN AUTENTICACION: cualquiera que conozca o adivine un session_id "
            "puede leer los datos de otro partido. Aceptable en local; antes de exponerlo, "
            "define API_KEY%s.",
            " y CORS_ALLOW_ORIGINS (ahora acepta cualquier origen)" if "*" in allowed_origins else "",
        )
    try:
        yield
    finally:
        session_manager.shutdown()
        workers.shutdown()


app = FastAPI(title="Football Copilot", version=FCOPILOT_VERSION, lifespan=lifespan)

allowed_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# UTILIDADES COMPARTIDAS
# ─────────────────────────────────────────────────────────────
def _http(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


#: Rutas que no exigen credencial ni con `API_KEY` puesta: sonda de vida y
#: preflight de CORS. Todo lo demás bajo /api y /ws la exige.
RUTAS_ABIERTAS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


def _credencial_valida(provided: Optional[str]) -> bool:
    """Comparación en tiempo constante: comparar con `==` filtra el prefijo."""
    return bool(API_KEY) and secrets.compare_digest(provided or "", API_KEY)


@app.middleware("http")
async def exigir_credencial(request: Request, call_next):
    """Frontera de confianza del servicio.

    Va en un middleware y no en una dependencia por ruta a propósito: una ruta
    nueva queda protegida sin que su autor se acuerde de nada. Olvidarlo deja de
    ser posible, que es la diferencia entre una regla y un guardia.
    """
    if not API_KEY or request.method == "OPTIONS" or request.url.path in RUTAS_ABIERTAS:
        return await call_next(request)
    provided = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if not _credencial_valida(provided):
        return JSONResponse({"detail": "credencial invalida o ausente"}, status_code=401)
    return await call_next(request)


def get_session_id(request: Request) -> str:
    """Resuelve el ``session_id`` desde la cabecera o el query string."""
    raw = request.headers.get("x-session-id") or request.query_params.get("session_id")
    try:
        return normalize_session_id(raw)
    except SessionIdError as exc:
        raise _http(400, str(exc)) from exc


def get_analyzer(session_id: str = Depends(get_session_id)) -> FootballAnalyzer:
    try:
        return session_manager.get(session_id)
    except SessionLimitError as exc:
        raise _http(429, str(exc)) from exc
    except DetectorUnavailable as exc:
        raise _http(503, str(exc)) from exc


def save_session(session_id: str, analyzer: FootballAnalyzer) -> None:
    session_manager.save(session_id, analyzer)


def validate_model_path(path: str) -> str:
    """Sólo se admiten pesos ``.pt`` existentes dentro del proyecto."""
    if not path.endswith(".pt"):
        raise _http(400, "El modelo debe ser un archivo .pt")
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise _http(400, "El modelo indicado no existe")
    # ``is_relative_to`` compara por componentes: "/proj-malicioso" ya no cuela
    # como si estuviera bajo "/proj".
    if not resolved.is_relative_to(MODEL_ROOT):
        raise _http(400, "El modelo debe estar dentro del proyecto")
    return str(resolved)


def assert_upload_size(size_bytes: int) -> None:
    if size_bytes <= 0:
        raise _http(400, "Archivo vacio")
    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        raise _http(413, f"Archivo demasiado grande. Limite: {MAX_UPLOAD_MB} MB")


def decode_image(data: bytes) -> "np.ndarray":
    if cv2 is None:  # pragma: no cover
        raise _http(503, "OpenCV no esta instalado en el servidor")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise _http(400, "No se pudo decodificar la imagen")
    return img


def target_size(analyzer: FootballAnalyzer) -> tuple:
    return int(analyzer.config["process_width"]), int(analyzer.config["process_height"])


async def run_in_worker(fn, *args):
    """Ejecuta trabajo pesado (YOLO) fuera del event loop, en el pool compartido."""
    return await asyncio.get_running_loop().run_in_executor(workers.get(), fn, *args)


# ─────────────────────────────────────────────────────────────
# ESTADO DEL SERVICIO
# ─────────────────────────────────────────────────────────────
@app.get("/health")
def health(session_id: Optional[str] = Query(default=None)):
    stats = session_manager.stats()
    analyzer = session_manager.peek(normalize_session_id(session_id)) if session_id else None
    status = analyzer.session_status() if analyzer else None
    return {
        "status": "ok",
        "version": FCOPILOT_VERSION,
        "uptime_s": round(time.time() - START_TIME, 1),
        "capabilities": {
            "yolo": YOLO_AVAILABLE,
            "sahi": SAHI_AVAILABLE,
            "norfair": NORFAIR_AVAILABLE,
            "bytetrack": BYTETRACK_AVAILABLE,
            "torch": TORCH_AVAILABLE,
            "osnet": osnet_weights_available(DEFAULTS["osnet_weight_path"]),
            "opencv": cv2 is not None,
        },
        "limits": {
            "auth_required": bool(API_KEY),
            "max_upload_mb": MAX_UPLOAD_MB,
            "max_concurrent_analyses": MAX_CONCURRENT_ANALYSES,
            "cors_any_origin": "*" in allowed_origins,
        },
        "sessions": {
            "count": stats["count"],
            "busy": stats["busy_count"],
            "ttl_s": stats["ttl_seconds"],
            "max": stats["max_sessions"],
            "cleaned": stats["cleaned"],
        },
        **shared_yolo_registry.stats(),
        **shared_osnet_registry.stats(),
        "session_id": session_id,
        "frame": analyzer.frame_count if analyzer else None,
        "fps_avg": round(float(np.mean(analyzer.fps_window)), 1) if analyzer and analyzer.fps_window else None,
        "model": analyzer.model_path if analyzer else None,
        "tracker_type": analyzer.tracker_type if analyzer else None,
        "detection_mode": analyzer.config["detection_mode"] if analyzer else None,
        "busy": bool(status["active_session"]) if status else None,
        "active_session": status["active_session"] if status else None,
        "active_for_s": status["active_for_s"] if status else None,
    }


@app.get("/api/sessions")
def list_sessions():
    return {"sessions": session_manager.list_sessions(), "stats": session_manager.stats()}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, purge_state: bool = True):
    try:
        normalized = normalize_session_id(session_id)
    except SessionIdError as exc:
        raise _http(400, str(exc)) from exc
    if not session_manager.delete(normalized, purge_state=purge_state):
        raise _http(404, "Sesion no encontrada")
    return {"ok": True, "session_id": normalized, "purge_state": purge_state}


# ─────────────────────────────────────────────────────────────
# JUGADORES
# ─────────────────────────────────────────────────────────────
@app.post("/api/player-name")
def set_player_name(data: PlayerNameRequest, session_id: str = Depends(get_session_id)):
    analyzer = get_analyzer(session_id)
    analyzer.update_name(data.track_id, data.name)
    save_session(session_id, analyzer)
    return {"ok": True}


@app.post("/api/player-team")
def set_player_team(data: PlayerTeamRequest, session_id: str = Depends(get_session_id)):
    analyzer = get_analyzer(session_id)
    analyzer.update_team(data.track_id, data.team)
    save_session(session_id, analyzer)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────
# CALIBRACIÓN
# ─────────────────────────────────────────────────────────────
@app.post("/api/calibrate")
def calibrate(data: CalibrationRequest, session_id: str = Depends(get_session_id)):
    """Escala simple (``pixels_per_meter``) u homografía con 4 puntos."""
    analyzer = get_analyzer(session_id)
    if data.img_points is not None or data.world_points is not None:
        if not data.img_points or not data.world_points:
            raise _http(400, "img_points y world_points son obligatorios juntos")
        if len(data.img_points) != 4 or len(data.world_points) != 4:
            raise _http(400, "La homografia requiere exactamente 4 puntos de imagen y 4 de campo")
        if any(len(p) != 2 for p in data.img_points + data.world_points):
            raise _http(400, "Cada punto debe tener 2 coordenadas")
        try:
            analyzer.set_homography(data.img_points, data.world_points)
        except CalibrationError as exc:
            raise _http(400, str(exc)) from exc
        save_session(session_id, analyzer)
        return {"ok": True, "mode": "homography"}

    if data.pixels_per_meter is None:
        raise _http(400, "Indica pixels_per_meter o los 4 puntos de homografia")
    analyzer.pixels_per_meter = float(data.pixels_per_meter)
    save_session(session_id, analyzer)
    return {"ok": True, "mode": "scale", "pixels_per_meter": analyzer.pixels_per_meter}


@app.get("/api/calibrate")
def get_calibration(session_id: str = Depends(get_session_id)):
    analyzer = get_analyzer(session_id)
    return {"calibrated": analyzer.is_calibrated, "pixels_per_meter": analyzer.pixels_per_meter}


@app.delete("/api/calibrate")
def clear_calibration(session_id: str = Depends(get_session_id)):
    analyzer = get_analyzer(session_id)
    analyzer.clear_homography()
    save_session(session_id, analyzer)
    return {"ok": True, "calibrated": False}


# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────
@app.get("/api/config")
def get_config(session_id: str = Depends(get_session_id)):
    analyzer = get_analyzer(session_id)
    config = analyzer.config
    return {
        "model": analyzer.model_path,
        "confidence": config["confidence"],
        "imgsz": config["imgsz"],
        "iou": config["iou"],
        "agnostic_nms": config["agnostic_nms"],
        "augment": config["augment"],
        "detection_mode": config["detection_mode"],
        "sahi_slice": config["sahi_slice"],
        "sahi_overlap": config["sahi_overlap"],
        "sahi_available": SAHI_AVAILABLE,
        "tracker_type": config["tracker_type"],
        "tracker_effective": analyzer.tracker_type,
        "norfair_dist": config["norfair_dist"],
        "norfair_hit_max": config["norfair_hit_max"],
        "norfair_available": NORFAIR_AVAILABLE,
        "bytetrack_available": BYTETRACK_AVAILABLE,
        "team_classifier": config["team_classifier"],
        "torch_available": TORCH_AVAILABLE,
        "osnet_weight_path": config["osnet_weight_path"],
        "osnet_available": osnet_weights_available(config["osnet_weight_path"]),
        "frame_skip": config["frame_skip"],
        "process_width": config["process_width"],
        "process_height": config["process_height"],
    }


@app.post("/api/config")
async def set_config(data: ConfigRequest, session_id: str = Depends(get_session_id)):
    analyzer = get_analyzer(session_id)
    raw = data.to_patch()
    if "model_path" in raw:
        raw["model_path"] = validate_model_path(raw["model_path"])
    try:
        patch = validate_config(raw)
    except ConfigError as exc:
        raise _http(400, str(exc)) from exc

    if patch.get("detection_mode") == "sahi" and not SAHI_AVAILABLE:
        raise _http(400, "SAHI no esta disponible en este entorno")
    if patch.get("tracker_type") == "norfair" and not NORFAIR_AVAILABLE:
        raise _http(400, "Norfair no esta disponible en este entorno")
    if patch.get("tracker_type") == "bytetrack" and not BYTETRACK_AVAILABLE:
        raise _http(400, "ByteTrack (supervision) no esta disponible en este entorno")
    if patch.get("team_classifier") == "osnet" and not osnet_weights_available(analyzer.config["osnet_weight_path"]):
        raise _http(400, "OSNet no esta disponible en este entorno")

    # Cargar un modelo o un clasificador puede tardar segundos: fuera del loop.
    try:
        result = await run_in_worker(analyzer.apply_config, patch)
    except DetectorUnavailable as exc:
        raise _http(503, str(exc)) from exc
    save_session(session_id, analyzer)
    return {"ok": True, **result}


# ─────────────────────────────────────────────────────────────
# INFORME / RESET
# ─────────────────────────────────────────────────────────────
@app.get("/api/export")
def export(session_id: str = Depends(get_session_id), include_positions: bool = True):
    return get_analyzer(session_id).get_export(include_positions=include_positions)


@app.get("/api/report")
def report(session_id: str = Depends(get_session_id)):
    """Informe agregado sin el rastro de posiciones (ligero para la UI)."""
    return get_analyzer(session_id).get_export(include_positions=False)


@app.post("/api/reset")
def reset(session_id: str = Depends(get_session_id), soft: bool = False):
    analyzer = get_analyzer(session_id)
    analyzer.soft_reset() if soft else analyzer.reset()
    save_session(session_id, analyzer)
    return {"ok": True, "soft": soft}


# ─────────────────────────────────────────────────────────────
# PREVIEW DE UN FRAME
# ─────────────────────────────────────────────────────────────
@app.post("/api/preview-frame")
async def preview_frame(
    frame: UploadFile = File(...),
    session_id: str = Depends(get_session_id),
    timestamp: float = Query(default=0.0, ge=0.0),
):
    """Detecta jugadores en un frame suelto para asignar equipos antes del análisis."""
    analyzer = get_analyzer(session_id)
    content_type = frame.content_type or ""
    if content_type and content_type not in ALLOWED_IMAGE_TYPES:
        raise _http(415, "Formato de imagen no soportado")
    data = await frame.read()
    await frame.close()
    assert_upload_size(len(data))
    img = cv2.resize(decode_image(data), target_size(analyzer))

    lease = f"{session_id}:preview"
    if not analyzer.try_acquire_session(lease):
        raise _http(409, "El analizador esta ocupado con otra tarea")
    try:
        analyzer.soft_reset()
        result = await run_in_worker(analyzer.process_frame, img, float(timestamp))
    except DetectorUnavailable as exc:
        raise _http(503, str(exc)) from exc
    finally:
        analyzer.release_session(lease)
    save_session(session_id, analyzer)
    return result


# ─────────────────────────────────────────────────────────────
# WEBSOCKET (cámara en vivo)
# ─────────────────────────────────────────────────────────────
@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    try:
        session_id = normalize_session_id(ws.query_params.get("session_id"))
        analyzer = session_manager.get(session_id)
    except (SessionIdError, SessionLimitError, DetectorUnavailable) as exc:
        await ws.send_text(json.dumps({"error": str(exc)}))
        await ws.close(code=1013)
        return

    if API_KEY and not _credencial_valida(
        ws.headers.get("x-api-key") or ws.query_params.get("api_key")
    ):
        # El middleware HTTP no cubre WebSockets: aquí se comprueba a mano.
        await ws.send_text(json.dumps({"error": "credencial invalida o ausente"}))
        await ws.close(code=1008)
        return

    lease = f"{session_id}:websocket"
    if not analyzer.try_acquire_session(lease):
        await ws.send_text(json.dumps({"error": "El analizador esta ocupado con otra tarea"}))
        await ws.close(code=1013)
        return

    started = time.monotonic()
    try:
        while True:
            data = await ws.receive_bytes()
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                await ws.send_text(json.dumps({"error": "frame ilegible"}))
                continue
            # Sin `timestamp`: esto es directo y no existe un tiempo de vídeo que
            # consultar. Pasarle el reloj como si fuera tiempo de vídeo etiquetaría
            # las métricas de webcam como comparables con las de un fichero, y no
            # lo son. El analizador registra la fuente `reloj` por su cuenta.
            result = await run_in_worker(analyzer.process_frame, frame)
            await ws.send_text(json.dumps(result))
    except WebSocketDisconnect:
        logger.info("WebSocket desconectado (%s)", session_id)
    except Exception as exc:  # pragma: no cover - errores de red
        logger.exception("WS error: %s", exc)
    finally:
        analyzer.release_session(lease)
        save_session(session_id, analyzer)


# ─────────────────────────────────────────────────────────────
# VÍDEO COMPLETO (NDJSON en streaming)
# ─────────────────────────────────────────────────────────────
async def _spool_upload(file: UploadFile) -> str:
    """Vuelca el vídeo a un temporal validando el tamaño mientras se recibe."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    total = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            assert_upload_size(total)
            tmp.write(chunk)
    except BaseException:
        tmp.close()
        os.unlink(tmp.name)
        raise
    finally:
        await file.close()
    tmp.close()
    assert_upload_size(total)
    return tmp.name


@app.post("/api/process-video")
async def process_video(file: UploadFile = File(...), session_id: str = Depends(get_session_id)):
    analyzer = get_analyzer(session_id)
    content_type = file.content_type or ""
    if content_type and not content_type.startswith("video/"):
        await file.close()
        raise _http(415, "El archivo debe ser un video")

    lease = f"{session_id}:video_analysis"
    if not analyzer.try_acquire_session(lease):
        await file.close()
        raise _http(409, "El analizador esta ocupado con otra tarea")

    # El lease de arriba impide dos análisis en la MISMA sesión; esto impide que
    # N sesiones saturen los WORKER_THREADS entre todas. Sin él, doce sesiones
    # subiendo a la vez ocupan doce ficheros temporales de hasta 1 GB y compiten
    # por dos hilos: nadie termina y el disco se llena.
    if not analysis_slots.acquire(blocking=False):
        analyzer.release_session(lease)
        await file.close()
        raise _http(
            429,
            f"El servicio ya esta analizando {MAX_CONCURRENT_ANALYSES} videos. Reintenta en unos minutos.",
        )

    try:
        tmp_path = await _spool_upload(file)
    except BaseException:
        analysis_slots.release()
        analyzer.release_session(lease)
        raise

    async def generate():
        cap = cv2.VideoCapture(tmp_path)
        analyzer.soft_reset()
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if not 1.0 <= video_fps <= 240.0:
            video_fps = 25.0
        frame_skip = int(analyzer.config["frame_skip"])
        size = target_size(analyzer)
        n = 0
        try:
            if not cap.isOpened():
                yield json.dumps({"error": "No se pudo abrir el video"}) + "\n"
                return
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                n += 1
                if frame_skip and n % (frame_skip + 1) != 0:
                    continue
                # El tiempo de vídeo es la base de todas las métricas: saltar
                # frames ya no altera velocidades ni distancias.
                video_time = n / video_fps
                result = await run_in_worker(analyzer.process_frame, cv2.resize(frame, size), video_time)
                result["video_time"] = round(video_time, 4)
                yield json.dumps(result) + "\n"
        except DetectorUnavailable as exc:
            yield json.dumps({"error": str(exc)}) + "\n"
        except Exception as exc:  # pragma: no cover - fallo inesperado de decodificación
            logger.exception("Error analizando video: %s", exc)
            yield json.dumps({"error": "Fallo durante el analisis del video"}) + "\n"
        finally:
            cap.release()
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_path)
            analyzer.release_session(lease)
            analysis_slots.release()
            save_session(session_id, analyzer)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


if __name__ == "__main__":
    uvicorn.run(
        "football_copilot_v2_backend:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
