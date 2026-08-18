"""Re-identificación por apariencia con OSNet (opcional, requiere PyTorch).

El módulo se importa siempre; si PyTorch no está instalado, ``TORCH_AVAILABLE``
es ``False`` y :class:`OSNetTeamClassifier` queda inutilizable pero no rompe el
arranque del backend.

Arquitectura OSNet x1.0 (torchreid / Tryolabs Soccer Analytics).
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict as _OD, defaultdict
from typing import Dict, List, Optional, Sequence

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

try:
    from sklearn.cluster import KMeans
except ImportError:  # pragma: no cover
    KMeans = None  # type: ignore[assignment]

logger = logging.getLogger("fcopilot.osnet")

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torchvision.transforms as T
    from PIL import Image as PILImage

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin torch
    TORCH_AVAILABLE = False

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
                logger.info("OSNet pesos cargados (%s/%s capas)", len(new_sd), len(msd))
            except Exception as exc:
                logger.warning("OSNet weight load error: %s", exc)
        else:
            logger.warning("OSNet pesos no encontrados: %s — usando pesos aleatorios", wp)
        model.eval().to(device)
        return model

    _OSNET_PREPROCESS = T.Compose([
        T.Resize((64, 32)),
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

else:  # pragma: no cover - sin torch no hay modelo
    _OSNetX1 = None
    _load_osnet = None
    _OSNET_PREPROCESS = None


class SharedOSNetRegistry:
    """Cachea los pesos OSNet para no recargarlos en cada sesión."""

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


shared_osnet_registry = SharedOSNetRegistry()


def osnet_weights_available(weight_path: str) -> bool:
    return TORCH_AVAILABLE and os.path.exists(os.path.abspath(os.path.expanduser(weight_path)))


class OSNetTeamClassifier:
    """Agrupa jugadores en dos equipos con embeddings de apariencia (512-d)."""

    name = "osnet"

    def __init__(self, weight_path: str, min_tracks: int = 4, min_frames: int = 3):
        self.is_fitted = False
        self.kmeans = None
        self.weight_path = weight_path
        self.min_tracks = min_tracks
        self.min_frames = min_frames
        self._embs: Dict[object, List[np.ndarray]] = defaultdict(list)
        self._labels: Dict[object, str] = {}
        self._device = "cpu"
        self._model = None
        try:
            self._model = shared_osnet_registry.get(weight_path)
        except Exception as exc:  # pragma: no cover - depende del entorno
            logger.warning("OSNet init error: %s", exc)

    @property
    def available(self) -> bool:
        return self._model is not None

    def _embed(self, frame: np.ndarray, bbox: Sequence[float]) -> Optional[np.ndarray]:
        if self._model is None or not TORCH_AVAILABLE or cv2 is None:
            return None
        x1, y1, x2, y2 = (int(round(v)) for v in bbox)
        if y2 - y1 < 20 or x2 - x1 < 10:
            return None
        crop = frame[max(0, y1):y2, max(0, x1):x2]
        if crop.size == 0:
            return None
        try:
            pil = PILImage.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            tensor = _OSNET_PREPROCESS(pil).unsqueeze(0).to(self._device).float()
            with torch.inference_mode():
                emb = self._model(tensor).cpu().numpy()[0]
            norm = float(np.linalg.norm(emb))
            return emb / norm if norm > 1e-12 else emb
        except Exception:  # pragma: no cover
            return None

    def fit(self, frame: np.ndarray, bboxes: Sequence[Sequence[float]]) -> None:
        """OSNet se ajusta de forma incremental desde :meth:`predict`."""

    def predict(self, frame: np.ndarray, bbox: Sequence[float], track_id: Optional[object] = None) -> str:
        emb = self._embed(frame, bbox)
        if emb is None:
            return self._labels.get(track_id, "unknown")
        key = track_id if track_id is not None else id(bbox)
        self._embs[key].append(emb)
        if len(self._embs[key]) > 30:
            self._embs[key].pop(0)
        if key in self._labels:
            return self._labels[key]

        ready = [k for k, v in self._embs.items() if len(v) >= self.min_frames]
        if len(ready) >= self.min_tracks:
            self._refit()
        return self._labels.get(key, "unknown")

    def _refit(self) -> None:
        if KMeans is None:
            return
        keys = list(self._embs.keys())
        aggregated = []
        for key in keys:
            mean = np.asarray(self._embs[key]).mean(axis=0)
            norm = float(np.linalg.norm(mean))
            aggregated.append(mean / norm if norm > 1e-12 else mean)
        X = np.asarray(aggregated)
        if len(X) < 2:
            return
        try:
            model = KMeans(n_clusters=2, n_init=2, random_state=42)
            model.fit(X)
            c0, c1 = model.cluster_centers_
            similarity = float(np.dot(c0, c1) / (np.linalg.norm(c0) * np.linalg.norm(c1) + 1e-12))
            if similarity > 0.95:
                # Los dos clusters son casi idénticos: no hay dos kits distintos.
                for key in keys:
                    self._labels[key] = "team_1"
            else:
                # Orden determinista para que las etiquetas no se intercambien.
                order = sorted(range(2), key=lambda i: tuple(np.round(model.cluster_centers_[i][:3], 4)))
                remap = {order[0]: "team_1", order[1]: "team_2"}
                for i, key in enumerate(keys):
                    self._labels[key] = remap[int(model.labels_[i])]
            self.kmeans = model
            self.is_fitted = True
        except Exception as exc:  # pragma: no cover
            logger.warning("OSNet refit error: %s", exc)
