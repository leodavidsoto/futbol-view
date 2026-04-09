"""
Football Copilot v2 — Backend
FastAPI + YOLOv8 + ByteTrack (supervision) + KMeans teams
+ Ball detection + Speed/Distance + Export

Optimizado para MacBook Pro 2018 i7 16GB (CPU)
"""

import asyncio
import concurrent.futures
import json
import os
import tempfile
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
OSNET_WEIGHT_PATH     = "repos/soccer-video-detection-ai-agent-main/weights/osnet_model.pth.tar-100"
MAX_TRACK_HISTORY     = 300
BALL_POSSESSION_DIST  = 90
FIELD_W_METERS        = 68.0
FIELD_H_METERS        = 105.0

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
    def __init__(self):
        self.is_fitted   = False
        self.kmeans: Optional[KMeans] = None
        self._embs: Dict[int, List[np.ndarray]] = defaultdict(list)
        self._labels: Dict[int, str]             = {}  # track_id → "team_1"|"team_2"
        self._model                              = None
        self._device                             = "cpu"
        if TORCH_AVAILABLE and _load_osnet is not None:
            try:
                self._model = _load_osnet(OSNET_WEIGHT_PATH, self._device)
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


def make_team_classifier():
    """Factory: crea el clasificador de equipos según TEAM_CLASSIFIER_TYPE."""
    if TEAM_CLASSIFIER_TYPE == "osnet":
        clf = OSNetTeamClassifier()
        if clf.available:
            print("✅  Clasificador: OSNet (apariencia)")
            return clf
        print("⚠️  OSNet no disponible, usando grass_kmeans")
    if TEAM_CLASSIFIER_TYPE in ("grass_kmeans", "osnet"):
        print("✅  Clasificador: Grass-aware KMeans")
        return GrassAwareTeamClassifier()
    print("✅  Clasificador: KMeans básico")
    return TeamClassifier()


# ─────────────────────────────────────────────────────────────
# MAIN ANALYZER
# ─────────────────────────────────────────────────────────────
class FootballAnalyzer:
    def __init__(self):
        print("⚽  Cargando modelo YOLO…")
        self.model = YOLO(YOLO_MODEL)
        self.model_path = YOLO_MODEL
        self.model.predict(np.zeros((64, 64, 3), dtype=np.uint8), verbose=False)

        self._init_tracker()
        self._init_sahi()
        self.team_clf   = make_team_classifier()
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
        print("✅  FootballAnalyzer listo")

    def reload_model(self, path: str):
        """Recarga el modelo YOLO desde un nuevo path sin reiniciar el servidor."""
        print(f"🔄  Cargando modelo: {path}")
        self.model = YOLO(path)
        self.model_path = path
        self.model.predict(np.zeros((64, 64, 3), dtype=np.uint8), verbose=False)
        self._init_sahi()
        print(f"✅  Modelo {path} listo")

    def _init_tracker(self):
        if TRACKER_TYPE == "norfair" and NORFAIR_AVAILABLE:
            # Norfair — distancia Euclidiana sobre centroides
            # Ideal para tomas aéreas donde el IoU puede ser ~0 entre frames
            self.tracker = NorfairTracker(
                distance_function="euclidean",
                distance_threshold=NORFAIR_DIST_THRESH,
                hit_counter_max=NORFAIR_HIT_MAX,
                initialization_delay=1,
            )
            self.ball_tracker = NorfairTracker(
                distance_function="euclidean",
                distance_threshold=NORFAIR_DIST_THRESH * 2,
                hit_counter_max=NORFAIR_HIT_MAX + 10,
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
                    r = NORFAIR_DIST_THRESH * 0.6
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
                confidence_threshold=CONFIDENCE_THRESHOLD,
                device="cpu",
            )
            print("✅  SAHI model inicializado")
        except Exception as e:
            print(f"⚠️  SAHI init error: {e}")

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
            conf=CONFIDENCE_THRESHOLD,
            iou=IOU_THRESHOLD,
            classes=[PERSON_CLASS, BALL_CLASS],
            imgsz=YOLO_IMGSZ,
            augment=AUGMENT,
            agnostic_nms=AGNOSTIC_NMS,
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
        self.sahi_model.confidence_threshold = CONFIDENCE_THRESHOLD

        result = get_sliced_prediction(
            frame,
            self.sahi_model,
            slice_height=SAHI_SLICE_SIZE,
            slice_width=SAHI_SLICE_SIZE,
            overlap_height_ratio=SAHI_OVERLAP,
            overlap_width_ratio=SAHI_OVERLAP,
            perform_standard_pred=True,   # también corre en el frame completo
            postprocess_class_agnostic=AGNOSTIC_NMS,
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
        fps = self._fps()
        self.frame_count += 1
        h, w = frame.shape[:2]

        # ── Detección (normal o SAHI) ────────────────────────
        if DETECTION_MODE == "sahi" and self.sahi_model is not None:
            person_xyxy, person_conf, ball_candidates = self._predict_sahi(frame)
        else:
            person_xyxy, person_conf, ball_candidates = self._predict_normal(frame)

        # ── Tracking unificado (Norfair o ByteTrack) ─────────
        player_tracks = self._track_players(person_xyxy, person_conf)

        # ── Auto-fit KMeans (no aplica a OSNet que entrena incremental) ──
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

            # Posición en coordenadas reales del campo (si hay homografía)
            world = self.pixel_to_world(cx, cy)
            if world:
                pos["wx"], pos["wy"] = world
                # Distancia real acumulada en metros
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

            # Si hay homografía, velocidad más precisa usando distancias reales
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

        # ── Balón (tracking unificado) ───────────────────────
        ball_out  = None
        ball_info = self._track_ball(ball_candidates)

        if ball_info:
            bcx, bcy, bx1, by1, bx2, by2 = ball_info

            self.ball_positions.append({"frame": self.frame_count, "x": bcx, "y": bcy})
            if len(self.ball_positions) > MAX_TRACK_HISTORY:
                self.ball_positions.pop(0)
            self.ball_last_seen = self.frame_count

            ball_world = self.pixel_to_world(bcx, bcy)

            # ── Posesión estilo Tryolabs ─────────────────────
            # Usa distancia real (metros) si hay homografía, sino píxeles
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

            # Acumular solo frames con posesión real (excluye "none")
            if possession != "none":
                self.possession_frames[possession] = \
                    self.possession_frames.get(possession, 0) + 1
            else:
                self.possession_frames["none"] = \
                    self.possession_frames.get("none", 0) + 1

            active = self.possession_frames["team_1"] + self.possession_frames["team_2"]
            total_pos = active or 1
            possession_pct = {
                "team_1": round(self.possession_frames["team_1"] / total_pos * 100, 1),
                "team_2": round(self.possession_frames["team_2"] / total_pos * 100, 1),
                "none":   round(self.possession_frames.get("none", 0) / (active + self.possession_frames.get("none",0) or 1) * 100, 1),
            }

            ball_out = {
                "center":         [bcx, bcy],
                "bbox":           [int(bx1), int(by1), int(bx2), int(by2)],
                "trail":          self.ball_positions[-30:],
                "possession":     possession,
                "possession_pct": possession_pct,
            }

        # ── Stats ────────────────────────────────────────────
        t1 = [p for p in players_out if p["team"] == "team_1"]
        t2 = [p for p in players_out if p["team"] == "team_2"]

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
            "possession_frames": self.possession_frames,
        }

    def update_name(self, track_id: str, name: str):
        self.player_names[track_id] = name
        tid = int(track_id)
        if tid in self.tracks:
            self.tracks[tid]["name"] = name

    def update_team(self, track_id: str, team: str):
        self.player_teams[track_id] = team
        tid = int(track_id)
        if tid in self.tracks:
            self.tracks[tid]["team"] = team

    def get_export(self) -> dict:
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
        src = np.float32(img_points)
        dst = np.float32(world_points)
        self.homography, _ = cv2.findHomography(src, dst)
        print(f"✅  Homografía calibrada con {len(img_points)} puntos")

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
        saved_teams = dict(self.player_teams)
        saved_names = dict(self.player_names)
        self._init_tracker()
        self.tracks = {}
        self.ball_positions = []
        self.ball_last_seen = None
        self.frame_count = 0
        self.fps_window = []
        self.clf_fitted = False
        self.team_clf = make_team_classifier()
        self.possession_frames = {"team_1": 0, "team_2": 0, "none": 0}
        self.player_teams = saved_teams
        self.player_names = saved_names

    def reset(self):
        """Reset completo, incluyendo asignaciones manuales."""
        self._init_tracker()
        self.tracks = {}
        self.ball_positions = []
        self.ball_last_seen = None
        self.frame_count = 0
        self.fps_window = []
        self.clf_fitted = False
        self.team_clf = make_team_classifier()
        self.possession_frames = {"team_1": 0, "team_2": 0, "none": 0}
        self.player_teams = {}
        self.player_names = {}

    def set_team_classifier(self, clf_type: str):
        """Cambia el tipo de clasificador de equipos en caliente."""
        global TEAM_CLASSIFIER_TYPE
        TEAM_CLASSIFIER_TYPE = clf_type
        self.clf_fitted = False
        self.team_clf = make_team_classifier()


# ─────────────────────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────────────────────
app     = FastAPI(title="Football Copilot v2", version="2.0.0")
analyzer = FootballAnalyzer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status":  "ok",
        "version": "2.0",
        "frame":   analyzer.frame_count,
        "fps_avg": round(float(np.mean(analyzer.fps_window)) if analyzer.fps_window else 0, 1),
    }


@app.post("/api/player-name")
async def set_player_name(data: dict):
    analyzer.update_name(str(data["track_id"]), data["name"])
    return {"ok": True}


@app.post("/api/player-team")
async def set_player_team(data: dict):
    """Asignación manual de equipo por track_id (override del clasificador automático)."""
    analyzer.update_team(str(data["track_id"]), data["team"])
    return {"ok": True}


@app.post("/api/calibrate")
async def calibrate(data: dict):
    """
    Calibración de campo.
    Modo 1 — escala simple:   { "pixels_per_meter": 8.0 }
    Modo 2 — homografía:      { "img_points": [[x,y]×4], "world_points": [[wx,wy]×4] }
    """
    if "img_points" in data and "world_points" in data:
        analyzer.set_homography(data["img_points"], data["world_points"])
        return {"ok": True, "mode": "homography"}
    else:
        analyzer.pixels_per_meter = float(data.get("pixels_per_meter", 8.0))
        return {"ok": True, "mode": "scale", "pixels_per_meter": analyzer.pixels_per_meter}

@app.get("/api/calibrate")
def get_calibration():
    return {
        "calibrated": analyzer.homography is not None,
        "pixels_per_meter": analyzer.pixels_per_meter,
    }


@app.get("/api/config")
def get_config():
    return {
        "model":             analyzer.model_path,
        "confidence":        CONFIDENCE_THRESHOLD,
        "imgsz":             YOLO_IMGSZ,
        "iou":               IOU_THRESHOLD,
        "agnostic_nms":      AGNOSTIC_NMS,
        "augment":           AUGMENT,
        "detection_mode":    DETECTION_MODE,
        "sahi_slice":        SAHI_SLICE_SIZE,
        "sahi_overlap":      SAHI_OVERLAP,
        "sahi_available":    SAHI_AVAILABLE,
        "tracker_type":      TRACKER_TYPE,
        "norfair_dist":      NORFAIR_DIST_THRESH,
        "norfair_hit_max":   NORFAIR_HIT_MAX,
        "norfair_available": NORFAIR_AVAILABLE,
        "team_classifier":   TEAM_CLASSIFIER_TYPE,
        "torch_available":   TORCH_AVAILABLE,
        "osnet_weight_path": OSNET_WEIGHT_PATH,
        "osnet_available":   TORCH_AVAILABLE and os.path.exists(os.path.abspath(OSNET_WEIGHT_PATH)),
    }


@app.post("/api/config")
async def set_config(data: dict):
    global CONFIDENCE_THRESHOLD, YOLO_IMGSZ, IOU_THRESHOLD
    global AGNOSTIC_NMS, AUGMENT, DETECTION_MODE, SAHI_SLICE_SIZE, SAHI_OVERLAP
    global TRACKER_TYPE, NORFAIR_DIST_THRESH, NORFAIR_HIT_MAX
    global TEAM_CLASSIFIER_TYPE

    reload_model   = False
    reinit_tracker = False

    if "model" in data and data["model"] != analyzer.model_path:
        loop = asyncio.get_running_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        await loop.run_in_executor(executor, analyzer.reload_model, data["model"])
        executor.shutdown(wait=False)
        reload_model = True

    if "tracker_type" in data and data["tracker_type"] != TRACKER_TYPE:
        TRACKER_TYPE = str(data["tracker_type"])
        reinit_tracker = True
    if "norfair_dist"    in data: NORFAIR_DIST_THRESH = int(data["norfair_dist"]); reinit_tracker = True
    if "norfair_hit_max" in data: NORFAIR_HIT_MAX     = int(data["norfair_hit_max"]); reinit_tracker = True

    if reinit_tracker:
        analyzer._init_tracker()

    if "confidence"     in data: CONFIDENCE_THRESHOLD = float(data["confidence"])
    if "imgsz"          in data: YOLO_IMGSZ           = int(data["imgsz"])
    if "iou"            in data: IOU_THRESHOLD         = float(data["iou"])
    if "agnostic_nms"   in data: AGNOSTIC_NMS          = bool(data["agnostic_nms"])
    if "augment"        in data: AUGMENT               = bool(data["augment"])
    if "detection_mode" in data: DETECTION_MODE        = str(data["detection_mode"])
    if "sahi_slice"     in data: SAHI_SLICE_SIZE       = int(data["sahi_slice"])
    if "sahi_overlap"   in data: SAHI_OVERLAP          = float(data["sahi_overlap"])

    if "team_classifier" in data and data["team_classifier"] != TEAM_CLASSIFIER_TYPE:
        loop2 = asyncio.get_running_loop()
        exec2 = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        await loop2.run_in_executor(exec2, analyzer.set_team_classifier, data["team_classifier"])
        exec2.shutdown(wait=False)

    return {"ok": True, "model_reloaded": reload_model, "tracker_reinited": reinit_tracker}


@app.get("/api/export")
def export():
    return analyzer.get_export()


@app.post("/api/reset")
def reset():
    analyzer.reset()
    return {"ok": True}


# ─── Preview de primer frame (JPEG → detección YOLO sin tracking completo) ───
@app.post("/api/preview-frame")
async def preview_frame(frame: UploadFile = File(...)):
    """
    Recibe un frame JPEG (primer frame del video), ejecuta YOLO + ByteTrack,
    y retorna las detecciones para que el usuario asigne equipos antes del análisis.
    Hace soft_reset para limpiar estado anterior pero preservar overrides previos.
    """
    data = await frame.read()
    arr  = np.frombuffer(data, np.uint8)
    img  = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return {"players": [], "ball": None, "stats": {}, "frame": 0, "fps": 0}
    img    = cv2.resize(img, (854, 480))
    loop   = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    analyzer.soft_reset()
    result = await loop.run_in_executor(executor, analyzer.process_frame, img)
    executor.shutdown(wait=False)
    return result


# ─── WebSocket (frames JPEG enviados por el cliente) ──────────
@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
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
        pass
    except Exception as e:
        print(f"[WS] Error: {e}")


# ─── Video file (NDJSON streaming response) ───────────────────
@app.post("/api/process-video")
async def process_video(file: UploadFile = File(...)):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp.write(await file.read())
    tmp.close()

    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    async def generate():
        cap = cv2.VideoCapture(tmp.name)
        analyzer.soft_reset()   # preserva overrides de equipo asignados en preview
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_skip = 2  # procesar 1 de cada 3 frames (~3x más rápido)
        n = 0
        try:
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
            os.unlink(tmp.name)
            executor.shutdown(wait=False)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


if __name__ == "__main__":
    uvicorn.run("football_copilot_v2_backend:app", host="0.0.0.0", port=8000, reload=False)
