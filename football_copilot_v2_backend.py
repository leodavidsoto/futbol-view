"""
Football Copilot v2 — Backend
FastAPI + YOLOv8 + ByteTrack (supervision) + KMeans teams
+ Ball detection + Speed/Distance + Export

Optimizado para MacBook Pro 2018 i7 16GB (CPU)
"""

import asyncio
import concurrent.futures
import gzip
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sklearn.cluster import KMeans
from ultralytics import YOLO
import supervision as sv

# SAHI (Sliced Aided Hyper Inference) — objetos pequeños en tomas aéreas
try:
    from sahi import AutoDetectionModel
    from sahi.predict import get_sliced_prediction
    SAHI_AVAILABLE = True
    print("✅  SAHI disponible")
except ImportError:
    SAHI_AVAILABLE = False
    print("⚠️  SAHI no instalado — pip install sahi")

# Norfair tracker (el que usa Tryolabs Soccer Analytics)
try:
    import norfair
    from norfair import Detection as NorfairDetection, Tracker as NorfairTracker
    NORFAIR_AVAILABLE = True
    print("✅  Norfair disponible")
except ImportError:
    NORFAIR_AVAILABLE = False
    print("⚠️  Norfair no instalado — pip install norfair")

# PyTorch (para OSNet re-identificación de apariencia)
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torchvision.transforms as T
    from PIL import Image as PILImage
    from collections import OrderedDict as _OD
    TORCH_AVAILABLE = True
    print("✅  PyTorch disponible — OSNet activable")
except ImportError:
    TORCH_AVAILABLE = False
    print("⚠️  PyTorch no instalado — OSNet no disponible (pip install torch torchvision pillow)")

# ─────────────────────────────────────────────────────────────
# CONFIG  (ajustable en caliente via /api/config)
# ─────────────────────────────────────────────────────────────
YOLO_MODEL            = "yolo11x.pt"  # cualquier .pt de ultralytics
YOLO_IMGSZ            = 1280          # 1280 detecta mejor objetos pequeños (aéreo)
CONFIDENCE_THRESHOLD  = 0.10          # bajo para tomas de drone
IOU_THRESHOLD         = 0.45          # NMS IoU
AGNOSTIC_NMS          = False         # NMS agnóstico a clase
AUGMENT               = False         # TTA: ~2x más lento, más detecciones
DETECTION_MODE        = "sahi"        # "normal" | "sahi"
SAHI_SLICE_SIZE       = 320           # tamaño del tile SAHI en píxeles
SAHI_OVERLAP          = 0.2           # solape entre tiles (0–0.5)
TRACKER_TYPE          = "norfair"     # "bytetrack" | "norfair"
NORFAIR_DIST_THRESH   = 50            # px — distancia máxima entre frames (Norfair)
NORFAIR_HIT_MAX       = 20            # frames sin detección antes de eliminar track
PERSON_CLASS          = 0             # COCO class: person
BALL_CLASS            = 32            # COCO class: sports ball
FPS_TARGET            = 20

# Clasificador de equipos
TEAM_CLASSIFIER_TYPE  = "grass_kmeans"   # "kmeans" | "grass_kmeans" | "osnet"
OSNET_WEIGHT_PATH     = "weights/osnet_x1_0_imagenet.pth"
MAX_TRACK_HISTORY     = 300
BALL_POSSESSION_DIST  = 90
FIELD_W_METERS        = 68.0
FIELD_H_METERS        = 105.0
MAX_UPLOAD_MB         = int(os.getenv("MAX_UPLOAD_MB", "1024"))
ALLOWED_TRACKERS      = {"bytetrack", "norfair"}
ALLOWED_DET_MODES     = {"normal", "sahi"}
ALLOWED_TEAM_CLFS     = {"kmeans", "grass_kmeans", "osnet"}
ALLOWED_MANUAL_TEAMS  = {"team_1", "team_2", "unknown"}
MODEL_ROOT            = os.path.abspath(".")
CONFIG_LOCK           = threading.RLock()
START_TIME            = time.time()
SESSION_ID_MAX_LEN    = 64
SESSION_TTL_SECONDS   = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
MAX_SESSIONS          = int(os.getenv("MAX_SESSIONS", "12"))
SESSION_STATE_DIR     = Path(os.getenv("SESSION_STATE_DIR", ".session_state"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("football_copilot")


def default_runtime_config() -> dict:
    return {
        "model_path": YOLO_MODEL,
        "imgsz": YOLO_IMGSZ,
        "confidence": CONFIDENCE_THRESHOLD,
        "iou": IOU_THRESHOLD,
        "agnostic_nms": AGNOSTIC_NMS,
        "augment": AUGMENT,
        "detection_mode": DETECTION_MODE,
        "sahi_slice": SAHI_SLICE_SIZE,
        "sahi_overlap": SAHI_OVERLAP,
        "tracker_type": TRACKER_TYPE,
        "norfair_dist": NORFAIR_DIST_THRESH,
        "norfair_hit_max": NORFAIR_HIT_MAX,
        "team_classifier": TEAM_CLASSIFIER_TYPE,
        "osnet_weight_path": OSNET_WEIGHT_PATH,
    }


def normalize_session_id(raw: Optional[str]) -> str:
    value = (raw or "default").strip()
    if not value or len(value) > SESSION_ID_MAX_LEN:
        raise HTTPException(status_code=400, detail="session_id invalido")
    if not all(ch.isalnum() or ch in ("-", "_") for ch in value):
        raise HTTPException(status_code=400, detail="session_id invalido")
    return value


class SharedYOLORegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._models: Dict[str, YOLO] = {}

    def get(self, model_path: str) -> YOLO:
        abs_path = os.path.abspath(model_path)
        with self._lock:
            model = self._models.get(abs_path)
            if model is None:
                logger.info("Cargando YOLO compartido: %s", abs_path)
                model = YOLO(abs_path)
                model.predict(np.zeros((64, 64, 3), dtype=np.uint8), verbose=False)
                self._models[abs_path] = model
            return model

    def stats(self) -> dict:
        with self._lock:
            return {"shared_yolo_models": len(self._models)}


class SharedOSNetRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._models: Dict[str, object] = {}

    def get(self, weight_path: str):
        if not TORCH_AVAILABLE or _load_osnet is None:
            return None
        abs_path = os.path.abspath(os.path.expanduser(weight_path))
        with self._lock:
            model = self._models.get(abs_path)
            if model is None:
                logger.info("Cargando OSNet compartido: %s", abs_path)
                model = _load_osnet(abs_path, "cpu")
                self._models[abs_path] = model
            return model

    def stats(self) -> dict:
        with self._lock:
            return {"shared_osnet_models": len(self._models)}


shared_yolo_registry = SharedYOLORegistry()
shared_osnet_registry = SharedOSNetRegistry()


def _validate_model_path(path: str) -> str:
    if not path.endswith(".pt"):
        raise HTTPException(status_code=400, detail="El modelo debe ser un archivo .pt")
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=400, detail="El modelo indicado no existe")
    if not abs_path.startswith(MODEL_ROOT):
        raise HTTPException(status_code=400, detail="El modelo debe estar dentro del proyecto")
    return abs_path


def _assert_upload_size(size_bytes: int):
    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail="Archivo vacio")
    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Archivo demasiado grande. Limite: {MAX_UPLOAD_MB} MB")


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
    model_config = ConfigDict(extra="ignore")
    model: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    imgsz: Optional[int] = Field(default=None, ge=320, le=2048)
    iou: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    agnostic_nms: Optional[bool] = None
    augment: Optional[bool] = None
    detection_mode: Optional[str] = None
    sahi_slice: Optional[int] = Field(default=None, ge=128, le=1024)
    sahi_overlap: Optional[float] = Field(default=None, ge=0.0, le=0.5)
    tracker_type: Optional[str] = None
    norfair_dist: Optional[int] = Field(default=None, ge=5, le=300)
    norfair_hit_max: Optional[int] = Field(default=None, ge=1, le=240)
    team_classifier: Optional[str] = None

    @field_validator("detection_mode")
    @classmethod
    def validate_detection_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in ALLOWED_DET_MODES:
            raise ValueError("detection_mode invalido")
        return value

    @field_validator("tracker_type")
    @classmethod
    def validate_tracker_type(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in ALLOWED_TRACKERS:
            raise ValueError("tracker_type invalido")
        return value

    @field_validator("team_classifier")
    @classmethod
    def validate_team_classifier(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in ALLOWED_TEAM_CLFS:
            raise ValueError("team_classifier invalido")
        return value

# ─────────────────────────────────────────────────────────────
# TEAM CLASSIFIER  (KMeans sobre color de camiseta)
# ─────────────────────────────────────────────────────────────
class TeamClassifier:
    """
    Clasifica equipo basándose en el color dominante del torso del jugador.
    Usa KMeans sobre espacio HSV para ser robusto ante variaciones de luz.
    Se auto-entrena con los primeros frames cuando hay ≥6 jugadores visibles.
    """

    def __init__(self):
        self.kmeans: Optional[KMeans] = None
        self.is_fitted = False

    def _extract_features(self, frame: np.ndarray, bbox: Tuple) -> Optional[np.ndarray]:
        x1, y1, x2, y2 = map(int, bbox)
        h = y2 - y1
        w = x2 - x1
        if h < 20 or w < 10:
            return None
        # Zona del torso: franja central superior del bbox
        torso = frame[y1 + int(h * 0.10): y1 + int(h * 0.60), x1:x2]
        if torso.size == 0:
            return None
        resized = cv2.resize(torso, (24, 24))
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        # Media por canal HSV como feature vector (3 valores)
        return hsv.reshape(-1, 3).mean(axis=0)

    def fit(self, frame: np.ndarray, bboxes: List[Tuple]):
        features = [self._extract_features(frame, b) for b in bboxes]
        features = [f for f in features if f is not None]
        if len(features) < 4:
            return
        X = np.array(features)
        self.kmeans = KMeans(n_clusters=2, random_state=42, n_init=10)
        self.kmeans.fit(X)
        self.is_fitted = True

    def predict(self, frame: np.ndarray, bbox: Tuple, track_id=None) -> str:
        if not self.is_fitted:
            return "unknown"
        f = self._extract_features(frame, bbox)
        if f is None:
            return "unknown"
        label = int(self.kmeans.predict([f])[0])
        return f"team_{label + 1}"


# ─────────────────────────────────────────────────────────────
# GRASS-AWARE TEAM CLASSIFIER
# Filtra píxeles verdes (césped) antes de clasificar por color de camiseta.
# Fuente: Football-Object-Detection / Roboflow Soccer Analytics
# ─────────────────────────────────────────────────────────────

def get_grass_color_from_frame(frame: np.ndarray) -> Optional[np.ndarray]:
    """Detecta el color del césped muestreando el centro del frame."""
    h, w = frame.shape[:2]
    center = frame[h // 3 : 2 * h // 3, w // 3 : 2 * w // 3]
    if center.size == 0:
        return None
    hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([30, 40, 40]), np.array([80, 255, 255]))
    if int(mask.sum()) < 500:
        return None
    grass_bgr = np.array(cv2.mean(center, mask=mask)[:3], dtype=np.float32)
    return cv2.cvtColor(np.uint8([[grass_bgr]]), cv2.COLOR_BGR2HSV)  # shape (1,1,3)


class GrassAwareTeamClassifier(TeamClassifier):
    """
    Igual que TeamClassifier pero filtra verde del campo y usa solo
    la mitad superior del bbox (camiseta, no piernas/césped).
    """
    def _extract_features(self, frame: np.ndarray, bbox: Tuple) -> Optional[np.ndarray]:
        x1, y1, x2, y2 = map(int, bbox)
        h, w = y2 - y1, x2 - x1
        if h < 20 or w < 10:
            return None
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        # Detectar color del cesped desde el frame
        grass_hsv = get_grass_color_from_frame(frame)
        if grass_hsv is not None:
            gH = int(grass_hsv[0, 0, 0])
            lower_green = np.array([max(0, gH - 12), 35, 35])
            upper_green = np.array([min(179, gH + 12), 255, 255])
        else:
            lower_green = np.array([30, 40, 40])
            upper_green = np.array([80, 255, 255])

        non_grass  = cv2.bitwise_not(cv2.inRange(hsv, lower_green, upper_green))
        upper_mask = np.zeros(crop.shape[:2], np.uint8)
        upper_mask[: crop.shape[0] // 2, :] = 255
        mask = cv2.bitwise_and(non_grass, upper_mask)

        if int(mask.sum()) < 100:
            # fallback: torso simple sin filtro
            torso_hsv = hsv[: h // 2]
            if torso_hsv.size == 0:
                return None
            return torso_hsv.reshape(-1, 3).mean(axis=0)

        return np.array(cv2.mean(crop, mask=mask)[:3])


# ─────────────────────────────────────────────────────────────
# OSNET  — Re-identificación por apariencia (512-dim embedding)
# Arquitectura: OSNetX1  de Tryolabs Soccer Analytics / torchreid
# Pesos: repos/soccer-video-detection-ai-agent-main/weights/osnet_model.pth.tar-100
# ─────────────────────────────────────────────────────────────

if TORCH_AVAILABLE:
    class _ConvLayer(nn.Module):
        def __init__(self, in_c, out_c, k, stride=1, padding=0, groups=1, IN=False):
            super().__init__()
            self.conv = nn.Conv2d(in_c, out_c, k, stride=stride, padding=padding, bias=False, groups=groups)
            self.bn   = nn.InstanceNorm2d(out_c, affine=True) if IN else nn.BatchNorm2d(out_c)
            self.relu = nn.ReLU()
        def forward(self, x): return self.relu(self.bn(self.conv(x)))

    class _Conv1x1(nn.Module):
        def __init__(self, in_c, out_c, stride=1):
            super().__init__()
            self.conv = nn.Conv2d(in_c, out_c, 1, stride=stride, bias=False)
            self.bn   = nn.BatchNorm2d(out_c); self.relu = nn.ReLU()
        def forward(self, x): return self.relu(self.bn(self.conv(x)))

    class _Conv1x1Lin(nn.Module):
        def __init__(self, in_c, out_c, stride=1):
            super().__init__()
            self.conv = nn.Conv2d(in_c, out_c, 1, stride=stride, bias=False)
            self.bn   = nn.BatchNorm2d(out_c)
        def forward(self, x): return self.bn(self.conv(x))

    class _LightConv3x3(nn.Module):
        def __init__(self, in_c, out_c):
            super().__init__()
            self.conv1 = nn.Conv2d(in_c, out_c, 1, bias=False)
            self.conv2 = nn.Conv2d(out_c, out_c, 3, padding=1, bias=False, groups=out_c)
            self.bn    = nn.BatchNorm2d(out_c); self.relu = nn.ReLU()
        def forward(self, x): return self.relu(self.bn(self.conv2(self.conv1(x))))

    class _ChannelGate(nn.Module):
        def __init__(self, in_c, reduction=16):
            super().__init__()
            self.pool = nn.AdaptiveAvgPool2d(1)
            self.fc1  = nn.Conv2d(in_c, in_c // reduction, 1, bias=True)
            self.relu = nn.ReLU()
            self.fc2  = nn.Conv2d(in_c // reduction, in_c, 1, bias=True)
            self.sig  = nn.Sigmoid()
        def forward(self, x):
            w = self.sig(self.fc2(self.relu(self.fc1(self.pool(x)))))
            return x * w

    class _OSBlock(nn.Module):
        def __init__(self, in_c, out_c, IN=False):
            super().__init__()
            mid = out_c // 4
            self.conv1 = _Conv1x1(in_c, mid)
            self.conv2a = _LightConv3x3(mid, mid)
            self.conv2b = nn.Sequential(_LightConv3x3(mid, mid), _LightConv3x3(mid, mid))
            self.conv2c = nn.Sequential(_LightConv3x3(mid, mid), _LightConv3x3(mid, mid), _LightConv3x3(mid, mid))
            self.conv2d = nn.Sequential(_LightConv3x3(mid, mid), _LightConv3x3(mid, mid), _LightConv3x3(mid, mid), _LightConv3x3(mid, mid))
            self.gate   = _ChannelGate(mid)
            self.conv3  = _Conv1x1Lin(mid, out_c)
            self.down   = _Conv1x1Lin(in_c, out_c) if in_c != out_c else None
            self.IN     = nn.InstanceNorm2d(out_c, affine=True) if IN else None

        def forward(self, x):
            identity = x
            x1  = self.conv1(x)
            x2  = self.gate(self.conv2a(x1)) + self.gate(self.conv2b(x1)) + \
                  self.gate(self.conv2c(x1)) + self.gate(self.conv2d(x1))
            x3  = self.conv3(x2)
            if self.down is not None:
                identity = self.down(identity)
            out = x3 + identity
            if self.IN is not None:
                out = self.IN(out)
            return F.relu(out)

    class _OSNetX1(nn.Module):
        def __init__(self, num_classes=1, feature_dim=512, IN=False):
            super().__init__()
            ch = [64, 256, 384, 512]
            self.conv1 = _ConvLayer(3, ch[0], 7, stride=2, padding=3, IN=IN)
            self.pool  = nn.MaxPool2d(3, stride=2, padding=1)
            self.conv2 = self._layer(ch[0], ch[1], 2, reduce=True, IN=IN)
            self.conv3 = self._layer(ch[1], ch[2], 2, reduce=True)
            self.conv4 = self._layer(ch[2], ch[3], 2, reduce=False)
            self.conv5 = _Conv1x1(ch[3], ch[3])
            self.gap   = nn.AdaptiveAvgPool2d(1)
            self.fc    = nn.Sequential(nn.Linear(ch[3], feature_dim), nn.BatchNorm1d(feature_dim), nn.ReLU(inplace=True))
            self.feature_dim = feature_dim
            self.classifier  = nn.Linear(feature_dim, num_classes)
            self._init()

        def _layer(self, in_c, out_c, n, reduce, IN=False):
            layers = [_OSBlock(in_c, out_c, IN=IN)]
            for _ in range(1, n):
                layers.append(_OSBlock(out_c, out_c, IN=IN))
            if reduce:
                layers.append(nn.Sequential(_Conv1x1(out_c, out_c), nn.AvgPool2d(2, stride=2)))
            return nn.Sequential(*layers)

        def _init(self):
            for m in self.modules():
                if isinstance(m, nn.Conv2d):
                    nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                    if m.bias is not None: nn.init.constant_(m.bias, 0)
                elif isinstance(m, (nn.BatchNorm2d, nn.BatchNorm1d, nn.InstanceNorm2d)):
                    nn.init.constant_(m.weight, 1); nn.init.constant_(m.bias, 0)
                elif isinstance(m, nn.Linear):
                    nn.init.normal_(m.weight, 0, 0.01)
                    if m.bias is not None: nn.init.constant_(m.bias, 0)

        def forward(self, x):
            x = self.pool(self.conv1(x))
            x = self.conv2(x); x = self.conv3(x); x = self.conv4(x); x = self.conv5(x)
            v = self.gap(x).view(x.size(0), -1)
            v = self.fc(v)
            if not self.training:
                return v
            return self.classifier(v)

    def _load_osnet(weight_path: str, device: str = "cpu") -> Optional["_OSNetX1"]:
        model = _OSNetX1(num_classes=1, feature_dim=512)
        wp = os.path.abspath(os.path.expanduser(weight_path))
        if os.path.exists(wp):
            try:
                ckpt = torch.load(wp, map_location=device, weights_only=False)
                sd   = ckpt.get("state_dict", ckpt)
                msd  = model.state_dict()
                new_sd = _OD()
                for k, v in sd.items():
                    key = k[7:] if k.startswith("module.") else k
                    if key in msd and msd[key].size() == v.size():
                        new_sd[key] = v
                msd.update(new_sd)
                model.load_state_dict(msd)
                print(f"✅  OSNet pesos cargados ({len(new_sd)}/{len(msd)} capas)")
            except Exception as e:
                print(f"⚠️  OSNet weight load error: {e}")
        else:
            print(f"⚠️  OSNet pesos no encontrados: {wp} — usando random init")
        model.eval().to(device)
        return model

    _OSNET_PREPROCESS = T.Compose([
        T.Resize((64, 32)),
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

else:
    _OSNetX1 = None
    _load_osnet = None
    _OSNET_PREPROCESS = None


class OSNetTeamClassifier:
    """
    Clasifica jugadores por equipo usando embeddings OSNet (re-ID de apariencia).
    Acumula embeddings por track_id y hace KMeans cuando hay suficientes datos.
    Fuente: Tryolabs Soccer Analytics / torchreid
    """
    def __init__(self, weight_path: str):
        self.is_fitted   = False
        self.kmeans: Optional[KMeans] = None
        self._embs: Dict[int, List[np.ndarray]] = defaultdict(list)
        self._labels: Dict[int, str]             = {}  # track_id → "team_1"|"team_2"
        self._model                              = None
        self._device                             = "cpu"
        self.weight_path                         = weight_path
        try:
            self._model = shared_osnet_registry.get(self.weight_path)
        except Exception as e:
            print(f"⚠️  OSNet init error: {e}")

    @property
    def available(self) -> bool:
        return self._model is not None

    def _embed(self, frame: np.ndarray, bbox: Tuple) -> Optional[np.ndarray]:
        if self._model is None or not TORCH_AVAILABLE:
            return None
        x1, y1, x2, y2 = map(int, bbox)
        if y2 - y1 < 20 or x2 - x1 < 10:
            return None
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        try:
            rgb  = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            pil  = PILImage.fromarray(rgb)
            t    = _OSNET_PREPROCESS(pil).unsqueeze(0).to(self._device).float()
            with torch.inference_mode():
                emb = self._model(t).cpu().numpy()[0]
            norm = np.linalg.norm(emb)
            return emb / norm if norm > 1e-12 else emb
        except Exception:
            return None

    def fit(self, frame: np.ndarray, bboxes: List[Tuple]):
        pass  # OSNet fits incrementally via predict()

    def predict(self, frame: np.ndarray, bbox: Tuple, track_id=None) -> str:
        emb = self._embed(frame, bbox)
        if emb is None:
            return "unknown"
        key = track_id if track_id is not None else id(bbox)
        self._embs[key].append(emb)
        if key in self._labels:
            return self._labels[key]

        # Re-entrenar cuando hay ≥4 tracks con ≥3 frames cada uno
        ready = [k for k, v in self._embs.items() if len(v) >= 3]
        if len(ready) >= 4:
            self._refit()
        return self._labels.get(key, "unknown")

    def _refit(self):
        keys = list(self._embs.keys())
        agg  = []
        for k in keys:
            embs = np.array(self._embs[k])
            m    = embs.mean(axis=0)
            n    = np.linalg.norm(m)
            agg.append(m / n if n > 1e-12 else m)
        X = np.array(agg)
        if len(X) < 2:
            return
        try:
            km = KMeans(n_clusters=2, n_init=2, random_state=42)
            km.fit(X)
            c0, c1 = km.cluster_centers_
            sim = np.dot(c0, c1) / (np.linalg.norm(c0) * np.linalg.norm(c1) + 1e-12)
            if sim > 0.95:
                for k in keys: self._labels[k] = "team_1"
            else:
                for i, k in enumerate(keys):
                    self._labels[k] = f"team_{int(km.labels_[i]) + 1}"
            self.kmeans     = km
            self.is_fitted  = True
        except Exception as e:
            print(f"⚠️  OSNet refit error: {e}")


def make_team_classifier(clf_type: str, osnet_weight_path: str):
    """Factory: crea el clasificador de equipos según el tipo configurado."""
    if clf_type == "osnet":
        clf = OSNetTeamClassifier(osnet_weight_path)
        if clf.available:
            print("✅  Clasificador: OSNet (apariencia)")
            return clf
        print("⚠️  OSNet no disponible, usando grass_kmeans")
    if clf_type in ("grass_kmeans", "osnet"):
        print("✅  Clasificador: Grass-aware KMeans")
        return GrassAwareTeamClassifier()
    print("✅  Clasificador: KMeans básico")
    return TeamClassifier()


# ─────────────────────────────────────────────────────────────
# MAIN ANALYZER
# ─────────────────────────────────────────────────────────────
class FootballAnalyzer:
    def __init__(self, config: Optional[dict] = None):
        self.config = {**default_runtime_config(), **(config or {})}
        logger.info("Cargando modelo YOLO inicial")
        self.model = shared_yolo_registry.get(self.config["model_path"])
        self.model_path = self.config["model_path"]

        self._init_tracker()
        self._init_sahi()
        self.team_clf   = make_team_classifier(self.config["team_classifier"], self.config["osnet_weight_path"])
        self.clf_fitted = False

        self.player_teams: Dict[str, str] = {}
        self.tracks: Dict[int, dict] = {}
        self.ball_positions: List[dict] = []
        self.ball_last_seen: Optional[int] = None

        self.frame_count = 0
        self.fps_window: List[float] = []
        self.last_t = time.time()
        self.player_names: Dict[str, str] = {}
        self.pixels_per_meter: float = 8.0

        self.possession_frames: Dict[str, int] = {"team_1": 0, "team_2": 0, "none": 0}
        self.homography: Optional[np.ndarray] = None   # homografía imagen→campo
        self.state_lock = threading.RLock()
        self.session_lock = threading.Lock()
        self.active_session: Optional[str] = None
        self.active_session_started_at: Optional[float] = None
        self.created_at = time.time()
        self.last_accessed_at = self.created_at
        self.metrics = {
            "frames_processed": 0,
            "last_total_ms": 0.0,
            "last_detect_ms": 0.0,
            "last_track_ms": 0.0,
            "last_classify_ms": 0.0,
            "last_ball_ms": 0.0,
            "avg_total_ms": 0.0,
            "avg_detect_ms": 0.0,
            "avg_track_ms": 0.0,
            "avg_classify_ms": 0.0,
            "avg_ball_ms": 0.0,
        }
        logger.info("FootballAnalyzer listo")

    def reload_model(self, path: str):
        """Recarga el modelo YOLO desde un nuevo path sin reiniciar el servidor."""
        logger.info("Recargando modelo: %s", path)
        self.model = shared_yolo_registry.get(path)
        self.model_path = path
        self.config["model_path"] = path
        self._init_sahi()
        logger.info("Modelo listo: %s", path)

    def try_acquire_session(self, session_name: str) -> bool:
        with self.session_lock:
            if self.active_session is None:
                self.active_session = session_name
                self.active_session_started_at = time.time()
                logger.info("Sesion adquirida: %s", session_name)
                return True
            if self.active_session == session_name:
                return True
            return False

    def release_session(self, session_name: str):
        with self.session_lock:
            if self.active_session == session_name:
                logger.info("Sesion liberada: %s", session_name)
                self.active_session = None
                self.active_session_started_at = None

    def session_status(self) -> dict:
        with self.session_lock:
            return {
                "active_session": self.active_session,
                "active_for_s": round(time.time() - self.active_session_started_at, 1)
                if self.active_session_started_at else 0.0,
                "idle_for_s": round(time.time() - self.last_accessed_at, 1),
                "created_at": self.created_at,
                "metrics": dict(self.metrics),
            }

    def touch(self):
        with self.session_lock:
            self.last_accessed_at = time.time()

    def is_idle_expired(self, ttl_seconds: int) -> bool:
        with self.session_lock:
            if self.active_session is not None:
                return False
            return (time.time() - self.last_accessed_at) > ttl_seconds

    def _init_tracker(self):
        tracker_type = self.config["tracker_type"]
        norfair_dist = self.config["norfair_dist"]
        norfair_hit_max = self.config["norfair_hit_max"]
        if tracker_type == "norfair" and NORFAIR_AVAILABLE:
            # Norfair — distancia Euclidiana sobre centroides
            # Ideal para tomas aéreas donde el IoU puede ser ~0 entre frames
            self.tracker = NorfairTracker(
                distance_function="euclidean",
                distance_threshold=norfair_dist,
                hit_counter_max=norfair_hit_max,
                initialization_delay=1,
            )
            self.ball_tracker = NorfairTracker(
                distance_function="euclidean",
                distance_threshold=norfair_dist * 2,
                hit_counter_max=norfair_hit_max + 10,
                initialization_delay=0,
            )
            self._using_norfair = True
        else:
            # ByteTrack — afinado para vista aérea
            self.tracker = sv.ByteTrack(
                track_activation_threshold=0.20,
                lost_track_buffer=60,
                minimum_matching_threshold=0.70,
                frame_rate=FPS_TARGET,
            )
            self.ball_tracker = sv.ByteTrack(
                track_activation_threshold=0.15,
                lost_track_buffer=90,
                minimum_matching_threshold=0.40,
                frame_rate=FPS_TARGET,
            )
            self._using_norfair = False

    # ──────────────────────────────────────────────────────
    # Tracking unificado: devuelve [(tid, x1, y1, x2, y2)]
    # ──────────────────────────────────────────────────────
    def _track_players(self, person_xyxy, person_conf):
        if self._using_norfair:
            dets = []
            for xyxy, conf in zip(person_xyxy, person_conf):
                cx = (xyxy[0] + xyxy[2]) / 2
                cy = (xyxy[1] + xyxy[3]) / 2
                dets.append(NorfairDetection(
                    points=np.array([[cx, cy]]),
                    scores=np.array([conf]),
                    data={"xyxy": xyxy},
                ))
            tracked = self.tracker.update(detections=dets)
            result = []
            for obj in tracked:
                # estimate da la posición Kalman predicha
                cx, cy = obj.estimate[0]
                # usar bbox de última detección si está disponible
                if obj.last_detection is not None and obj.last_detection.data:
                    x1, y1, x2, y2 = obj.last_detection.data["xyxy"]
                else:
                    r = self.config["norfair_dist"] * 0.6
                    x1, y1, x2, y2 = cx - r, cy - r, cx + r, cy + r
                result.append((obj.id, float(x1), float(y1), float(x2), float(y2)))
            return result
        else:
            if person_xyxy:
                sv_det = sv.Detections(
                    xyxy=np.array(person_xyxy),
                    confidence=np.array(person_conf),
                    class_id=np.zeros(len(person_xyxy), dtype=int),
                )
                tracked = self.tracker.update_with_detections(sv_det)
            else:
                tracked = self.tracker.update_with_detections(sv.Detections.empty())
            return [(int(tracked.tracker_id[i]), *tracked.xyxy[i]) for i in range(len(tracked))]

    def _track_ball(self, ball_candidates):
        """Devuelve (bcx, bcy, bx1, by1, bx2, by2) o None."""
        if self._using_norfair:
            dets = []
            for xyxy, conf in ball_candidates:
                cx = (xyxy[0] + xyxy[2]) / 2
                cy = (xyxy[1] + xyxy[3]) / 2
                dets.append(NorfairDetection(
                    points=np.array([[cx, cy]]),
                    scores=np.array([conf]),
                    data={"xyxy": xyxy},
                ))
            tracked = self.ball_tracker.update(detections=dets)
            if tracked:
                obj = tracked[0]
                cx, cy = obj.estimate[0]
                if obj.last_detection is not None and obj.last_detection.data:
                    x1, y1, x2, y2 = obj.last_detection.data["xyxy"]
                else:
                    x1, y1, x2, y2 = cx - 15, cy - 15, cx + 15, cy + 15
                return int(cx), int(cy), float(x1), float(y1), float(x2), float(y2)
            return None
        else:
            if ball_candidates:
                ball_sv = sv.Detections(
                    xyxy=np.array([c[0] for c in ball_candidates]),
                    confidence=np.array([c[1] for c in ball_candidates]),
                    class_id=np.zeros(len(ball_candidates), dtype=int),
                )
                tracked = self.ball_tracker.update_with_detections(ball_sv)
            else:
                tracked = self.ball_tracker.update_with_detections(sv.Detections.empty())
            if len(tracked) > 0:
                conf = tracked.confidence
                best = int(np.argmax(conf)) if conf is not None and len(tracked) > 1 else 0
                bx1, by1, bx2, by2 = tracked.xyxy[best]
                return int((bx1+bx2)/2), int((by1+by2)/2), float(bx1), float(by1), float(bx2), float(by2)
            return None

    def _init_sahi(self):
        """Inicializa el modelo SAHI para sliced inference."""
        self.sahi_model = None
        if not SAHI_AVAILABLE:
            return
        try:
            self.sahi_model = AutoDetectionModel.from_pretrained(
                model_type="ultralytics",
                model_path=self.model_path,
                confidence_threshold=self.config["confidence"],
                device="cpu",
            )
            logger.info("SAHI inicializado")
        except Exception as e:
            logger.warning("SAHI init error: %s", e)

    # ──────────────────────────────────────────────────────
    # Utilidades
    # ──────────────────────────────────────────────────────
    def _fps(self) -> float:
        now = time.time()
        dt = now - self.last_t
        self.last_t = now
        fps = 1.0 / max(dt, 1e-6)
        self.fps_window.append(fps)
        if len(self.fps_window) > 30:
            self.fps_window.pop(0)
        return float(np.mean(self.fps_window))

    def _update_metrics(self, detect_ms: float, track_ms: float, classify_ms: float, ball_ms: float, total_ms: float):
        self.metrics["frames_processed"] += 1
        n = self.metrics["frames_processed"]
        self.metrics["last_detect_ms"] = round(detect_ms, 2)
        self.metrics["last_track_ms"] = round(track_ms, 2)
        self.metrics["last_classify_ms"] = round(classify_ms, 2)
        self.metrics["last_ball_ms"] = round(ball_ms, 2)
        self.metrics["last_total_ms"] = round(total_ms, 2)
        self.metrics["avg_detect_ms"] = round(((self.metrics["avg_detect_ms"] * (n - 1)) + detect_ms) / n, 2)
        self.metrics["avg_track_ms"] = round(((self.metrics["avg_track_ms"] * (n - 1)) + track_ms) / n, 2)
        self.metrics["avg_classify_ms"] = round(((self.metrics["avg_classify_ms"] * (n - 1)) + classify_ms) / n, 2)
        self.metrics["avg_ball_ms"] = round(((self.metrics["avg_ball_ms"] * (n - 1)) + ball_ms) / n, 2)
        self.metrics["avg_total_ms"] = round(((self.metrics["avg_total_ms"] * (n - 1)) + total_ms) / n, 2)

    def serialize_state(self) -> dict:
        with self.state_lock, self.session_lock:
            return {
                "config": self.config,
                "model_path": self.model_path,
                "player_teams": self.player_teams,
                "player_names": self.player_names,
                "tracks": self.tracks,
                "ball_positions": self.ball_positions,
                "ball_last_seen": self.ball_last_seen,
                "frame_count": self.frame_count,
                "fps_window": self.fps_window,
                "pixels_per_meter": self.pixels_per_meter,
                "possession_frames": self.possession_frames,
                "homography": self.homography.tolist() if self.homography is not None else None,
                "created_at": self.created_at,
                "last_accessed_at": self.last_accessed_at,
                "metrics": self.metrics,
            }

    def load_state(self, data: dict):
        with self.state_lock, self.session_lock:
            self.config = {**default_runtime_config(), **data.get("config", {})}
            self.model_path = data.get("model_path", self.config["model_path"])
            self.model = shared_yolo_registry.get(self.model_path)
            self._init_tracker()
            self._init_sahi()
            self.team_clf = make_team_classifier(self.config["team_classifier"], self.config["osnet_weight_path"])
            self.clf_fitted = False
            self.player_teams = {str(k): v for k, v in data.get("player_teams", {}).items()}
            self.player_names = {str(k): v for k, v in data.get("player_names", {}).items()}
            self.tracks = {int(k): v for k, v in data.get("tracks", {}).items()}
            self.ball_positions = data.get("ball_positions", [])
            self.ball_last_seen = data.get("ball_last_seen")
            self.frame_count = int(data.get("frame_count", 0))
            self.fps_window = [float(v) for v in data.get("fps_window", [])][-30:]
            self.pixels_per_meter = float(data.get("pixels_per_meter", 8.0))
            self.possession_frames = data.get("possession_frames", {"team_1": 0, "team_2": 0, "none": 0})
            self.homography = np.array(data["homography"], dtype=np.float32) if data.get("homography") is not None else None
            self.created_at = float(data.get("created_at", time.time()))
            self.last_accessed_at = float(data.get("last_accessed_at", time.time()))
            self.metrics.update(data.get("metrics", {}))

    def _speed_kmh(self, positions: List[dict], fps: float) -> float:
        if len(positions) < 3 or fps < 1:
            return 0.0
        pts = positions[-min(8, len(positions)):]
        p1, p2 = pts[0], pts[-1]
        dx = (p2["x"] - p1["x"]) / self.pixels_per_meter
        dy = (p2["y"] - p1["y"]) / self.pixels_per_meter
        dist_m = np.sqrt(dx ** 2 + dy ** 2)
        t_sec  = (len(pts) - 1) / fps
        return round(dist_m / max(t_sec, 1e-6) * 3.6, 1)

    def _update_distance(self, track_id: int, pos: dict):
        positions = self.tracks[track_id]["positions"]
        if len(positions) >= 2:
            p1 = positions[-2]
            dx = (pos["x"] - p1["x"]) / self.pixels_per_meter
            dy = (pos["y"] - p1["y"]) / self.pixels_per_meter
            step = np.sqrt(dx ** 2 + dy ** 2)
            self.tracks[track_id]["total_dist"] = round(
                self.tracks[track_id]["total_dist"] + step, 1
            )

    # ──────────────────────────────────────────────────────
    # Inferencia — Normal
    # ──────────────────────────────────────────────────────
    def _predict_normal(self, frame):
        results = self.model.predict(
            frame,
            conf=self.config["confidence"],
            iou=self.config["iou"],
            classes=[PERSON_CLASS, BALL_CLASS],
            imgsz=self.config["imgsz"],
            augment=self.config["augment"],
            agnostic_nms=self.config["agnostic_nms"],
            verbose=False,
        )[0]
        person_xyxy, person_conf, ball_candidates = [], [], []
        for box in results.boxes:
            cls  = int(box.cls[0])
            xyxy = box.xyxy[0].cpu().numpy()
            conf = float(box.conf[0])
            if cls == PERSON_CLASS:
                person_xyxy.append(xyxy)
                person_conf.append(conf)
            elif cls == BALL_CLASS:
                ball_candidates.append((xyxy, conf))
        return person_xyxy, person_conf, ball_candidates

    # ──────────────────────────────────────────────────────
    # Inferencia — SAHI (tiles solapados para objetos pequeños)
    # ──────────────────────────────────────────────────────
    def _predict_sahi(self, frame):
        if self.sahi_model is None:
            return self._predict_normal(frame)

        # Actualizar umbral de confianza en caliente
        self.sahi_model.confidence_threshold = self.config["confidence"]

        result = get_sliced_prediction(
            frame,
            self.sahi_model,
            slice_height=self.config["sahi_slice"],
            slice_width=self.config["sahi_slice"],
            overlap_height_ratio=self.config["sahi_overlap"],
            overlap_width_ratio=self.config["sahi_overlap"],
            perform_standard_pred=True,   # también corre en el frame completo
            postprocess_class_agnostic=self.config["agnostic_nms"],
            verbose=0,
        )

        person_xyxy, person_conf, ball_candidates = [], [], []
        for pred in result.object_prediction_list:
            bbox = pred.bbox
            xyxy = np.array([bbox.minx, bbox.miny, bbox.maxx, bbox.maxy], dtype=float)
            conf = float(pred.score.value)
            cid  = int(pred.category.id)
            if cid == PERSON_CLASS:
                person_xyxy.append(xyxy)
                person_conf.append(conf)
            elif cid == BALL_CLASS:
                ball_candidates.append((xyxy, conf))
        return person_xyxy, person_conf, ball_candidates

    # ──────────────────────────────────────────────────────
    # Frame principal
    # ──────────────────────────────────────────────────────
    def process_frame(self, frame: np.ndarray) -> dict:
        with self.state_lock:
            total_start = time.perf_counter()
            fps = self._fps()
            self.frame_count += 1
            h, w = frame.shape[:2]

            # ── Detección (normal o SAHI) ────────────────────────
            detect_start = time.perf_counter()
            if self.config["detection_mode"] == "sahi" and self.sahi_model is not None:
                person_xyxy, person_conf, ball_candidates = self._predict_sahi(frame)
            else:
                person_xyxy, person_conf, ball_candidates = self._predict_normal(frame)
            detect_ms = (time.perf_counter() - detect_start) * 1000

            # ── Tracking unificado (Norfair o ByteTrack) ─────────
            track_start = time.perf_counter()
            player_tracks = self._track_players(person_xyxy, person_conf)
            track_ms = (time.perf_counter() - track_start) * 1000

            # ── Auto-fit KMeans (no aplica a OSNet que entrena incremental) ──
            classify_start = time.perf_counter()
            _is_osnet = isinstance(self.team_clf, OSNetTeamClassifier)
            if not self.clf_fitted and not _is_osnet and len(player_tracks) >= 4:
                bboxes = [(x1, y1, x2, y2) for _, x1, y1, x2, y2 in player_tracks]
                self.team_clf.fit(frame, bboxes)
                self.clf_fitted = True
            if _is_osnet and self.team_clf.is_fitted:
                self.clf_fitted = True

            # ── Procesar jugadores ──────────────────────────────
            players_out = []
            for tid, x1, y1, x2, y2 in player_tracks:
                cx = int((x1 + x2) / 2)
                cy = int((y1 + y2) / 2)

                team = self.player_teams.get(str(tid)) or (
                    self.team_clf.predict(frame, (x1, y1, x2, y2), track_id=tid)
                    if (self.clf_fitted or _is_osnet) else "unknown"
                )

                if tid not in self.tracks:
                    self.tracks[tid] = {
                        "team":       team,
                        "name":       self.player_names.get(str(tid), f"#{tid}"),
                        "positions":  [],
                        "total_dist": 0.0,
                    }
                else:
                    if team != "unknown":
                        self.tracks[tid]["team"] = team

                if str(tid) in self.player_names:
                    self.tracks[tid]["name"] = self.player_names[str(tid)]

                pos = {"frame": self.frame_count, "x": cx, "y": cy}

                world = self.pixel_to_world(cx, cy)
                if world:
                    pos["wx"], pos["wy"] = world
                    prev_positions = self.tracks[tid]["positions"]
                    if len(prev_positions) >= 2 and "wx" in prev_positions[-1]:
                        pp = prev_positions[-1]
                        dm = np.sqrt((world[0]-pp["wx"])**2 + (world[1]-pp["wy"])**2)
                        self.tracks[tid]["total_dist_world"] = round(
                            self.tracks[tid].get("total_dist_world", 0.0) + dm, 1
                        )

                self._update_distance(tid, pos)
                self.tracks[tid]["positions"].append(pos)
                if len(self.tracks[tid]["positions"]) > MAX_TRACK_HISTORY:
                    self.tracks[tid]["positions"].pop(0)

                speed = self._speed_kmh(self.tracks[tid]["positions"], fps)

                if world and len(self.tracks[tid]["positions"]) >= 3:
                    world_pts = [p for p in self.tracks[tid]["positions"][-8:] if "wx" in p]
                    if len(world_pts) >= 3:
                        p1, p2 = world_pts[0], world_pts[-1]
                        dm = np.sqrt((p2["wx"]-p1["wx"])**2 + (p2["wy"]-p1["wy"])**2)
                        t = (len(world_pts)-1) / max(fps, 1)
                        speed = round(dm / max(t, 1e-6) * 3.6, 1)

                total_dist = self.tracks[tid].get("total_dist_world", self.tracks[tid]["total_dist"])

                players_out.append({
                    "track_id":     tid,
                    "name":         self.tracks[tid]["name"],
                    "team":         self.tracks[tid]["team"],
                    "bbox":         [int(x1), int(y1), int(x2), int(y2)],
                    "center":       [cx, cy],
                    "world_pos":    list(world) if world else None,
                    "speed_kmh":    speed,
                    "total_dist_m": total_dist,
                    "trail":        self.tracks[tid]["positions"][-20:],
                })
            classify_ms = (time.perf_counter() - classify_start) * 1000

            ball_start = time.perf_counter()
            ball_out  = None
            ball_info = self._track_ball(ball_candidates)

            if ball_info:
                bcx, bcy, bx1, by1, bx2, by2 = ball_info

                self.ball_positions.append({"frame": self.frame_count, "x": bcx, "y": bcy})
                if len(self.ball_positions) > MAX_TRACK_HISTORY:
                    self.ball_positions.pop(0)
                self.ball_last_seen = self.frame_count

                ball_world = self.pixel_to_world(bcx, bcy)

                possession = "none"
                min_d = float("inf")
                closest_team = "none"
                POSS_THRESH = 3.0 if self.homography is not None else BALL_POSSESSION_DIST
                for p in players_out:
                    if self.homography is not None and p["world_pos"] and ball_world:
                        d = np.hypot(p["world_pos"][0]-ball_world[0], p["world_pos"][1]-ball_world[1])
                    else:
                        d = np.hypot(p["center"][0] - bcx, p["center"][1] - bcy)
                    if d < min_d:
                        min_d = d
                        closest_team = p["team"]
                if min_d < POSS_THRESH and closest_team not in ("none", "unknown"):
                    possession = closest_team

                if possession != "none":
                    self.possession_frames[possession] = self.possession_frames.get(possession, 0) + 1
                else:
                    self.possession_frames["none"] = self.possession_frames.get("none", 0) + 1

                active = self.possession_frames["team_1"] + self.possession_frames["team_2"]
                total_pos = active or 1
                possession_pct = {
                    "team_1": round(self.possession_frames["team_1"] / total_pos * 100, 1),
                    "team_2": round(self.possession_frames["team_2"] / total_pos * 100, 1),
                    "none":   round(self.possession_frames.get("none", 0) / (active + self.possession_frames.get("none", 0) or 1) * 100, 1),
                }

                ball_out = {
                    "center":         [bcx, bcy],
                    "bbox":           [int(bx1), int(by1), int(bx2), int(by2)],
                    "trail":          self.ball_positions[-30:],
                    "possession":     possession,
                    "possession_pct": possession_pct,
                }
            ball_ms = (time.perf_counter() - ball_start) * 1000

            t1 = [p for p in players_out if p["team"] == "team_1"]
            t2 = [p for p in players_out if p["team"] == "team_2"]
            total_ms = (time.perf_counter() - total_start) * 1000
            self._update_metrics(detect_ms, track_ms, classify_ms, ball_ms, total_ms)

            return {
                "frame":     self.frame_count,
                "fps":       round(fps, 1),
                "players":   players_out,
                "ball":      ball_out,
                "stats": {
                    "total_players":    len(players_out),
                    "team_1_count":     len(t1),
                    "team_2_count":     len(t2),
                    "classifier_ready": self.clf_fitted,
                },
                "timings_ms": {
                    "detect": self.metrics["last_detect_ms"],
                    "track": self.metrics["last_track_ms"],
                    "classify": self.metrics["last_classify_ms"],
                    "ball": self.metrics["last_ball_ms"],
                    "total": self.metrics["last_total_ms"],
                },
                "possession_frames": self.possession_frames,
            }

    def update_name(self, track_id: str, name: str):
        with self.state_lock:
            self.player_names[track_id] = name
            tid = int(track_id)
            if tid in self.tracks:
                self.tracks[tid]["name"] = name

    def update_team(self, track_id: str, team: str):
        with self.state_lock:
            self.player_teams[track_id] = team
            tid = int(track_id)
            if tid in self.tracks:
                self.tracks[tid]["team"] = team

    def get_export(self) -> dict:
        with self.state_lock:
            return {
                "exported_at":   time.strftime("%Y-%m-%dT%H:%M:%S"),
                "total_frames":  self.frame_count,
                "possession_pct": {
                    k: round(v / max(sum(self.possession_frames.values()), 1) * 100, 1)
                    for k, v in self.possession_frames.items()
                },
                "players": {
                    str(tid): {
                        "name":          d["name"],
                        "team":          d["team"],
                        "total_dist_m":  d["total_dist"],
                        "positions":     d["positions"],
                    }
                    for tid, d in self.tracks.items()
                },
            }

    # ──────────────────────────────────────────────────────
    # Homografía / Calibración de campo
    # Mapea coordenadas de imagen → coordenadas reales (metros)
    # ──────────────────────────────────────────────────────
    def set_homography(self, img_points: List[List[float]], world_points: List[List[float]]):
        """
        Recibe 4 puntos de imagen y sus correspondientes coordenadas de campo en metros.
        Calcula la homografía y la guarda para transformar posiciones de jugadores.
        img_points: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] en píxeles
        world_points: [[wx1,wy1],...] en metros (p.ej. esquinas del campo)
        """
        with self.state_lock:
            src = np.float32(img_points)
            dst = np.float32(world_points)
            self.homography, _ = cv2.findHomography(src, dst)
        logger.info("Homografia calibrada con %s puntos", len(img_points))

    def pixel_to_world(self, px: float, py: float) -> Optional[Tuple[float, float]]:
        """Transforma un punto de imagen a coordenadas de campo en metros."""
        if self.homography is None:
            return None
        pt = np.float32([[[px, py]]])
        world = cv2.perspectiveTransform(pt, self.homography)[0][0]
        return float(world[0]), float(world[1])

    def world_dist_m(self, track_id: int) -> float:
        """Distancia acumulada en metros reales usando homografía (si disponible)."""
        if self.homography is None or track_id not in self.tracks:
            return self.tracks.get(track_id, {}).get("total_dist", 0.0)
        return self.tracks[track_id].get("total_dist_world", self.tracks[track_id]["total_dist"])

    def soft_reset(self):
        """Reset de tracking pero PRESERVA asignaciones manuales de equipo y nombres."""
        with self.state_lock:
            saved_teams = dict(self.player_teams)
            saved_names = dict(self.player_names)
            self._init_tracker()
            self.tracks = {}
            self.ball_positions = []
            self.ball_last_seen = None
            self.frame_count = 0
            self.fps_window = []
            self.clf_fitted = False
            self.team_clf = make_team_classifier(self.config["team_classifier"], self.config["osnet_weight_path"])
            self.possession_frames = {"team_1": 0, "team_2": 0, "none": 0}
            self.player_teams = saved_teams
            self.player_names = saved_names

    def reset(self):
        """Reset completo, incluyendo asignaciones manuales."""
        with self.state_lock:
            self._init_tracker()
            self.tracks = {}
            self.ball_positions = []
            self.ball_last_seen = None
            self.frame_count = 0
            self.fps_window = []
            self.clf_fitted = False
            self.team_clf = make_team_classifier(self.config["team_classifier"], self.config["osnet_weight_path"])
            self.possession_frames = {"team_1": 0, "team_2": 0, "none": 0}
            self.player_teams = {}
            self.player_names = {}

    def set_team_classifier(self, clf_type: str):
        """Cambia el tipo de clasificador de equipos en caliente."""
        with self.state_lock:
            self.config["team_classifier"] = clf_type
            self.clf_fitted = False
            self.team_clf = make_team_classifier(self.config["team_classifier"], self.config["osnet_weight_path"])


# ─────────────────────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────────────────────
class SessionManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: Dict[str, FootballAnalyzer] = {}
        SESSION_STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _state_path(self, session_id: str) -> Path:
        return SESSION_STATE_DIR / f"{session_id}.json.gz"

    def save(self, session_id: str, analyzer: FootballAnalyzer):
        path = self._state_path(session_id)
        tmp_path = path.with_suffix(".json.gz.tmp")
        data = analyzer.serialize_state()
        with gzip.open(tmp_path, "wt", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=True)
        tmp_path.replace(path)

    def delete(self, session_id: str, purge_state: bool = True) -> bool:
        removed = False
        with self._lock:
            analyzer = self._sessions.pop(session_id, None)
            removed = analyzer is not None
        if purge_state:
            path = self._state_path(session_id)
            if path.exists():
                path.unlink()
                removed = True
        return removed

    def list_sessions(self) -> List[dict]:
        with self._lock:
            self._cleanup_expired_locked()
            items = []
            for sid, analyzer in self._sessions.items():
                items.append({
                    "session_id": sid,
                    **analyzer.session_status(),
                    "frame_count": analyzer.frame_count,
                    "model": analyzer.model_path,
                })
            return sorted(items, key=lambda item: item["session_id"])

    def _cleanup_expired_locked(self) -> int:
        expired = [sid for sid, analyzer in self._sessions.items() if analyzer.is_idle_expired(SESSION_TTL_SECONDS)]
        for sid in expired:
            self._sessions.pop(sid, None)
            logger.info("Sesion expirada y eliminada: %s", sid)
        return len(expired)

    def get(self, session_id: str) -> FootballAnalyzer:
        with self._lock:
            self._cleanup_expired_locked()
            analyzer = self._sessions.get(session_id)
            if analyzer is None:
                if len(self._sessions) >= MAX_SESSIONS:
                    raise HTTPException(status_code=429, detail=f"Limite de sesiones activas alcanzado ({MAX_SESSIONS})")
                analyzer = FootballAnalyzer()
                path = self._state_path(session_id)
                if path.exists():
                    try:
                        with gzip.open(path, "rt", encoding="utf-8") as fh:
                            analyzer.load_state(json.load(fh))
                        logger.info("Sesion restaurada desde disco: %s", session_id)
                    except Exception as exc:
                        logger.warning("No se pudo restaurar la sesion %s: %s", session_id, exc)
                self._sessions[session_id] = analyzer
                logger.info("Sesion creada: %s", session_id)
            analyzer.touch()
            return analyzer

    def stats(self) -> dict:
        with self._lock:
            cleaned = self._cleanup_expired_locked()
            busy = 0
            sessions = {}
            for key, analyzer in self._sessions.items():
                status = analyzer.session_status()
                if status["active_session"] is not None:
                    busy += 1
                sessions[key] = status
            return {
                "count": len(self._sessions),
                "busy_count": busy,
                "cleaned": cleaned,
                "ttl_seconds": SESSION_TTL_SECONDS,
                "max_sessions": MAX_SESSIONS,
                "sessions": sessions,
            }


def get_request_session_id(request: Request) -> str:
    return normalize_session_id(
        request.headers.get("x-session-id") or request.query_params.get("session_id")
    )


app     = FastAPI(title="Football Copilot v2", version="2.0.0")
session_manager = SessionManager()

allowed_origins = [origin.strip() for origin in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(request: Request):
    manager_stats = session_manager.stats()
    registry_stats = {}
    registry_stats.update(shared_yolo_registry.stats())
    registry_stats.update(shared_osnet_registry.stats())
    session_id = request.query_params.get("session_id")
    analyzer = session_manager.get(normalize_session_id(session_id)) if session_id else None
    session = analyzer.session_status() if analyzer else None
    return {
        "status":  "ok",
        "version": "2.0",
        "uptime_s": round(time.time() - START_TIME, 1),
        "sahi_available": SAHI_AVAILABLE,
        "norfair_available": NORFAIR_AVAILABLE,
        "osnet_available": TORCH_AVAILABLE and os.path.exists(os.path.abspath(OSNET_WEIGHT_PATH)),
        "session_count": manager_stats["count"],
        "busy_sessions": manager_stats["busy_count"],
        "session_ttl_s": manager_stats["ttl_seconds"],
        "max_sessions": manager_stats["max_sessions"],
        "sessions_cleaned": manager_stats["cleaned"],
        **registry_stats,
        "session_id": session_id,
        "frame": analyzer.frame_count if analyzer else None,
        "fps_avg": round(float(np.mean(analyzer.fps_window)) if analyzer and analyzer.fps_window else 0, 1) if analyzer else None,
        "model": analyzer.model_path if analyzer else None,
        "tracker_type": analyzer.config["tracker_type"] if analyzer else None,
        "detection_mode": analyzer.config["detection_mode"] if analyzer else None,
        "busy": session["active_session"] is not None if session else None,
        "active_session": session["active_session"] if session else None,
        "active_for_s": session["active_for_s"] if session else None,
    }


@app.get("/api/sessions")
def list_sessions():
    return {
        "sessions": session_manager.list_sessions(),
        "stats": session_manager.stats(),
    }


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, purge_state: bool = True):
    normalized = normalize_session_id(session_id)
    deleted = session_manager.delete(normalized, purge_state=purge_state)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")
    return {"ok": True, "session_id": normalized, "purge_state": purge_state}


@app.post("/api/player-name")
async def set_player_name(data: PlayerNameRequest, request: Request):
    session_id = get_request_session_id(request)
    analyzer = session_manager.get(session_id)
    analyzer.update_name(str(data.track_id), data.name)
    session_manager.save(session_id, analyzer)
    return {"ok": True}


@app.post("/api/player-team")
async def set_player_team(data: PlayerTeamRequest, request: Request):
    """Asignación manual de equipo por track_id (override del clasificador automático)."""
    session_id = get_request_session_id(request)
    analyzer = session_manager.get(session_id)
    analyzer.update_team(str(data.track_id), data.team)
    session_manager.save(session_id, analyzer)
    return {"ok": True}


@app.post("/api/calibrate")
async def calibrate(data: CalibrationRequest, request: Request):
    """
    Calibración de campo.
    Modo 1 — escala simple:   { "pixels_per_meter": 8.0 }
    Modo 2 — homografía:      { "img_points": [[x,y]×4], "world_points": [[wx,wy]×4] }
    """
    session_id = get_request_session_id(request)
    analyzer = session_manager.get(session_id)
    if data.img_points is not None or data.world_points is not None:
        if not data.img_points or not data.world_points:
            raise HTTPException(status_code=400, detail="img_points y world_points son obligatorios juntos")
        if len(data.img_points) != 4 or len(data.world_points) != 4:
            raise HTTPException(status_code=400, detail="La homografia requiere exactamente 4 puntos de imagen y 4 de campo")
        if any(len(point) != 2 for point in data.img_points + data.world_points):
            raise HTTPException(status_code=400, detail="Cada punto debe tener 2 coordenadas")
        analyzer.set_homography(data.img_points, data.world_points)
        session_manager.save(session_id, analyzer)
        return {"ok": True, "mode": "homography"}
    pixels_per_meter = data.pixels_per_meter or 8.0
    analyzer.pixels_per_meter = float(pixels_per_meter)
    session_manager.save(session_id, analyzer)
    return {"ok": True, "mode": "scale", "pixels_per_meter": analyzer.pixels_per_meter}

@app.get("/api/calibrate")
def get_calibration(request: Request):
    analyzer = session_manager.get(get_request_session_id(request))
    return {
        "calibrated": analyzer.homography is not None,
        "pixels_per_meter": analyzer.pixels_per_meter,
    }


@app.get("/api/config")
def get_config(request: Request):
    analyzer = session_manager.get(get_request_session_id(request))
    return {
        "model":             analyzer.model_path,
        "confidence":        analyzer.config["confidence"],
        "imgsz":             analyzer.config["imgsz"],
        "iou":               analyzer.config["iou"],
        "agnostic_nms":      analyzer.config["agnostic_nms"],
        "augment":           analyzer.config["augment"],
        "detection_mode":    analyzer.config["detection_mode"],
        "sahi_slice":        analyzer.config["sahi_slice"],
        "sahi_overlap":      analyzer.config["sahi_overlap"],
        "sahi_available":    SAHI_AVAILABLE,
        "tracker_type":      analyzer.config["tracker_type"],
        "norfair_dist":      analyzer.config["norfair_dist"],
        "norfair_hit_max":   analyzer.config["norfair_hit_max"],
        "norfair_available": NORFAIR_AVAILABLE,
        "team_classifier":   analyzer.config["team_classifier"],
        "torch_available":   TORCH_AVAILABLE,
        "osnet_weight_path": analyzer.config["osnet_weight_path"],
        "osnet_available":   TORCH_AVAILABLE and os.path.exists(os.path.abspath(analyzer.config["osnet_weight_path"])),
    }


@app.post("/api/config")
async def set_config(data: ConfigRequest, request: Request):
    session_id = get_request_session_id(request)
    analyzer = session_manager.get(session_id)
    payload = data.model_dump(exclude_none=True)
    reload_model   = False
    reinit_tracker = False

    with CONFIG_LOCK:
        if "model" in payload and payload["model"] != analyzer.model_path:
            model_path = _validate_model_path(payload["model"])
            loop = asyncio.get_running_loop()
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                await loop.run_in_executor(executor, analyzer.reload_model, model_path)
            finally:
                executor.shutdown(wait=False)
            reload_model = True

        if "tracker_type" in payload and payload["tracker_type"] != analyzer.config["tracker_type"]:
            analyzer.config["tracker_type"] = str(payload["tracker_type"])
            reinit_tracker = True
        if "norfair_dist" in payload:
            analyzer.config["norfair_dist"] = int(payload["norfair_dist"])
            reinit_tracker = True
        if "norfair_hit_max" in payload:
            analyzer.config["norfair_hit_max"] = int(payload["norfair_hit_max"])
            reinit_tracker = True

        if reinit_tracker:
            analyzer._init_tracker()

        if "confidence" in payload:
            analyzer.config["confidence"] = float(payload["confidence"])
        if "imgsz" in payload:
            analyzer.config["imgsz"] = int(payload["imgsz"])
        if "iou" in payload:
            analyzer.config["iou"] = float(payload["iou"])
        if "agnostic_nms" in payload:
            analyzer.config["agnostic_nms"] = bool(payload["agnostic_nms"])
        if "augment" in payload:
            analyzer.config["augment"] = bool(payload["augment"])
        if "detection_mode" in payload:
            if payload["detection_mode"] == "sahi" and not SAHI_AVAILABLE:
                raise HTTPException(status_code=400, detail="SAHI no esta disponible en este entorno")
            analyzer.config["detection_mode"] = str(payload["detection_mode"])
        if "sahi_slice" in payload:
            analyzer.config["sahi_slice"] = int(payload["sahi_slice"])
        if "sahi_overlap" in payload:
            analyzer.config["sahi_overlap"] = float(payload["sahi_overlap"])

        if "team_classifier" in payload and payload["team_classifier"] != analyzer.config["team_classifier"]:
            if payload["team_classifier"] == "osnet" and not (TORCH_AVAILABLE and os.path.exists(os.path.abspath(analyzer.config["osnet_weight_path"]))):
                raise HTTPException(status_code=400, detail="OSNet no esta disponible en este entorno")
            loop2 = asyncio.get_running_loop()
            exec2 = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                await loop2.run_in_executor(exec2, analyzer.set_team_classifier, payload["team_classifier"])
            finally:
                exec2.shutdown(wait=False)

    session_manager.save(session_id, analyzer)
    return {"ok": True, "model_reloaded": reload_model, "tracker_reinited": reinit_tracker}


@app.get("/api/export")
def export(request: Request):
    analyzer = session_manager.get(get_request_session_id(request))
    return analyzer.get_export()


@app.post("/api/reset")
def reset(request: Request):
    session_id = get_request_session_id(request)
    analyzer = session_manager.get(session_id)
    analyzer.reset()
    session_manager.save(session_id, analyzer)
    return {"ok": True}


# ─── Preview de primer frame (JPEG → detección YOLO sin tracking completo) ───
@app.post("/api/preview-frame")
async def preview_frame(request: Request, frame: UploadFile = File(...)):
    """
    Recibe un frame JPEG (primer frame del video), ejecuta YOLO + ByteTrack,
    y retorna las detecciones para que el usuario asigne equipos antes del análisis.
    Hace soft_reset para limpiar estado anterior pero preservar overrides previos.
    """
    session_id = get_request_session_id(request)
    analyzer = session_manager.get(session_id)
    content_type = frame.content_type or ""
    if content_type and content_type not in {"image/jpeg", "image/jpg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Formato de imagen no soportado")
    data = await frame.read()
    await frame.close()
    _assert_upload_size(len(data))
    arr  = np.frombuffer(data, np.uint8)
    img  = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="No se pudo decodificar la imagen")
    img    = cv2.resize(img, (854, 480))
    loop   = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    if not analyzer.try_acquire_session(f"{session_id}:preview"):
        executor.shutdown(wait=False)
        raise HTTPException(status_code=409, detail="El analizador esta ocupado con otra sesion")
    analyzer.soft_reset()
    try:
        result = await loop.run_in_executor(executor, analyzer.process_frame, img)
    finally:
        analyzer.release_session(f"{session_id}:preview")
        executor.shutdown(wait=False)
    session_manager.save(session_id, analyzer)
    return result


# ─── WebSocket (frames JPEG enviados por el cliente) ──────────
@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    session_id = normalize_session_id(ws.query_params.get("session_id"))
    analyzer = session_manager.get(session_id)
    if not analyzer.try_acquire_session(f"{session_id}:websocket"):
        await ws.send_text(json.dumps({"error": "El analizador esta ocupado con otra sesion"}))
        await ws.close(code=1013)
        return
    try:
        while True:
            data  = await ws.receive_bytes()
            arr   = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue
            result = analyzer.process_frame(frame)
            await ws.send_text(json.dumps(result))
    except WebSocketDisconnect:
        logger.info("WebSocket desconectado")
    except Exception as e:
        logger.exception("WS error: %s", e)
    finally:
        analyzer.release_session(f"{session_id}:websocket")
        session_manager.save(session_id, analyzer)


# ─── Video file (NDJSON streaming response) ───────────────────
@app.post("/api/process-video")
async def process_video(request: Request, file: UploadFile = File(...)):
    session_id = get_request_session_id(request)
    analyzer = session_manager.get(session_id)
    content_type = file.content_type or ""
    if content_type and not content_type.startswith("video/"):
        raise HTTPException(status_code=415, detail="El archivo debe ser un video")
    if not analyzer.try_acquire_session(f"{session_id}:video_analysis"):
        await file.close()
        raise HTTPException(status_code=409, detail="El analizador esta ocupado con otra sesion")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp_path = tmp.name
    total_bytes = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            _assert_upload_size(total_bytes)
            tmp.write(chunk)
    except Exception:
        analyzer.release_session(f"{session_id}:video_analysis")
        raise
    finally:
        tmp.close()
        await file.close()

    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    async def generate():
        cap = cv2.VideoCapture(tmp_path)
        analyzer.soft_reset()   # preserva overrides de equipo asignados en preview
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_skip = 2  # procesar 1 de cada 3 frames (~3x más rápido)
        n = 0
        try:
            if not cap.isOpened():
                yield json.dumps({"error": "No se pudo abrir el video"}) + "\n"
                return
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                n += 1
                if frame_skip and n % (frame_skip + 1) != 0:
                    continue
                # Reducir resolución para CPU
                frame = cv2.resize(frame, (854, 480))
                # Ejecutar YOLO en thread para no bloquear el event loop
                result = await loop.run_in_executor(executor, analyzer.process_frame, frame)
                result["video_time"] = round(n / video_fps, 4)  # tiempo en video para sync frontend
                yield json.dumps(result) + "\n"
        finally:
            cap.release()
            os.unlink(tmp_path)
            executor.shutdown(wait=False)
            analyzer.release_session(f"{session_id}:video_analysis")
            session_manager.save(session_id, analyzer)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


if __name__ == "__main__":
    uvicorn.run("football_copilot_v2_backend:app", host="0.0.0.0", port=8000, reload=False)
