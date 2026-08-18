"""Clasificación de equipos por color de camiseta.

Mejoras respecto de la versión anterior:

* **Se entrena con muestras de varios frames**, no con el primer frame que
  tuviera 4 jugadores: el reparto en clusters es mucho más estable.
* **Etiquetas deterministas.** KMeans devuelve índices arbitrarios, así que los
  centroides se ordenan por color; ``team_1`` sigue siendo ``team_1`` después de
  cada reajuste en lugar de intercambiarse con ``team_2``.
* **Voto temporal por track.** La camiseta de un jugador no cambia entre
  frames: se devuelve la etiqueta mayoritaria de sus últimas observaciones, lo
  que elimina el parpadeo verde/rojo cuando un jugador se cruza con otro.
* **Filtrado de césped** en la variante *grass aware*, tomando el tono real del
  campo en cada frame.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:  # pragma: no cover - OpenCV está siempre presente en producción
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

try:  # pragma: no cover
    from sklearn.cluster import KMeans
except ImportError:  # pragma: no cover
    KMeans = None  # type: ignore[assignment]

UNKNOWN = "unknown"
BBox = Sequence[float]


def get_grass_color_hue(frame: np.ndarray) -> Optional[int]:
    """Tono HSV dominante del césped, muestreando el centro del frame."""
    if cv2 is None or frame is None or frame.size == 0:
        return None
    h, w = frame.shape[:2]
    center = frame[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
    if center.size == 0:
        return None
    hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([30, 40, 40]), np.array([80, 255, 255]))
    if int(np.count_nonzero(mask)) < 200:
        return None
    grass_bgr = np.array(cv2.mean(center, mask=mask)[:3], dtype=np.uint8).reshape(1, 1, 3)
    return int(cv2.cvtColor(grass_bgr, cv2.COLOR_BGR2HSV)[0, 0, 0])


def _crop(frame: np.ndarray, bbox: BBox) -> Optional[np.ndarray]:
    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
    h, w = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 6 or y2 - y1 < 12:
        return None
    crop = frame[y1:y2, x1:x2]
    return crop if crop.size else None


class ColorTeamClassifier:
    """KMeans de 2 clusters sobre el color medio HSV del torso."""

    name = "kmeans"

    def __init__(self, min_samples: int = 24, vote_window: int = 15, refit_every: int = 120):
        self.min_samples = max(4, int(min_samples))
        self.refit_every = max(1, int(refit_every))
        self.kmeans = None
        self.is_fitted = False
        self._features: List[np.ndarray] = []
        self._votes: Dict[object, Deque[str]] = defaultdict(lambda: deque(maxlen=max(1, int(vote_window))))
        self._since_fit = 0
        self._order: Tuple[int, int] = (0, 1)

    # ── Features ───────────────────────────────────────────────────────
    def _extract_features(self, frame: np.ndarray, bbox: BBox) -> Optional[np.ndarray]:
        if cv2 is None:
            return None
        crop = _crop(frame, bbox)
        if crop is None:
            return None
        torso = crop[int(crop.shape[0] * 0.10): int(crop.shape[0] * 0.60)]
        if torso.size == 0:
            return None
        hsv = cv2.cvtColor(cv2.resize(torso, (24, 24)), cv2.COLOR_BGR2HSV)
        return hsv.reshape(-1, 3).mean(axis=0).astype(np.float64)

    # ── Entrenamiento ──────────────────────────────────────────────────
    #: Separación mínima entre centroides (unidades HSV) para aceptar el ajuste.
    min_separation = 8.0

    def _fit_features(self) -> None:
        if KMeans is None or len(self._features) < self.min_samples:
            return
        X = np.asarray(self._features[-600:], dtype=np.float64)
        if len(np.unique(np.round(X, 2), axis=0)) < 2:
            # Todas las camisetas se ven igual (frame plano o un solo equipo):
            # forzar dos clusters sólo produciría etiquetas al azar.
            return
        model = KMeans(n_clusters=2, random_state=42, n_init=10)
        model.fit(X)
        # Orden determinista de clusters: por tono y luego por valor. Sin esto,
        # cada reajuste podría intercambiar las etiquetas de los dos equipos.
        centers = model.cluster_centers_
        if float(np.linalg.norm(centers[0] - centers[1])) < self.min_separation:
            # Los dos grupos son el mismo color: se sigue acumulando muestras.
            return
        order = sorted(range(2), key=lambda i: (round(float(centers[i][0]), 3), round(float(centers[i][2]), 3)))
        self._order = (order.index(0), order.index(1))
        self.kmeans = model
        self.is_fitted = True
        self._since_fit = 0

    def fit(self, frame: np.ndarray, bboxes: Sequence[BBox]) -> None:
        """Acumula las cajas de un frame y reajusta si hay muestras suficientes."""
        for bbox in bboxes:
            features = self._extract_features(frame, bbox)
            if features is not None:
                self._features.append(features)
        self._fit_features()

    def _raw_label(self, features: np.ndarray) -> str:
        cluster = int(self.kmeans.predict(features.reshape(1, -1))[0])
        return f"team_{self._order[cluster] + 1}"

    # ── Predicción ─────────────────────────────────────────────────────
    def predict(self, frame: np.ndarray, bbox: BBox, track_id: Optional[object] = None) -> str:
        features = self._extract_features(frame, bbox)
        if features is None:
            return self._vote(track_id)
        self._features.append(features)
        self._since_fit += 1

        if not self.is_fitted:
            if len(self._features) >= self.min_samples:
                self._fit_features()
            if not self.is_fitted:
                return UNKNOWN
        elif self._since_fit >= self.refit_every:
            self._fit_features()

        label = self._raw_label(features)
        if track_id is None:
            return label
        self._votes[track_id].append(label)
        return self._vote(track_id)

    def _vote(self, track_id: Optional[object]) -> str:
        if track_id is None:
            return UNKNOWN
        votes = self._votes.get(track_id)
        if not votes:
            return UNKNOWN
        return Counter(votes).most_common(1)[0][0]

    @property
    def sample_count(self) -> int:
        return len(self._features)


class GrassAwareTeamClassifier(ColorTeamClassifier):
    """Ignora los píxeles de césped y mira sólo la mitad superior de la caja."""

    name = "grass_kmeans"

    def _extract_features(self, frame: np.ndarray, bbox: BBox) -> Optional[np.ndarray]:
        if cv2 is None:
            return None
        crop = _crop(frame, bbox)
        if crop is None:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        hue = get_grass_color_hue(frame)
        if hue is None:
            lower, upper = np.array([30, 40, 40]), np.array([80, 255, 255])
        else:
            lower = np.array([max(0, hue - 12), 35, 35])
            upper = np.array([min(179, hue + 12), 255, 255])

        non_grass = cv2.bitwise_not(cv2.inRange(hsv, lower, upper))
        upper_half = np.zeros(crop.shape[:2], np.uint8)
        upper_half[: crop.shape[0] // 2, :] = 255
        mask = cv2.bitwise_and(non_grass, upper_half)

        if int(np.count_nonzero(mask)) < 20:
            torso = hsv[: crop.shape[0] // 2]
            if torso.size == 0:
                return None
            return torso.reshape(-1, 3).mean(axis=0).astype(np.float64)
        return np.array(cv2.mean(hsv, mask=mask)[:3], dtype=np.float64)
