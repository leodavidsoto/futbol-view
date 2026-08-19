"""Tracker de centroides sin dependencias externas.

Norfair y ByteTrack siguen siendo los trackers recomendados, pero ambos son
opcionales: si no están instalados el backend se quedaba sin arrancar. Este
tracker cubre ese hueco (asociación voraz por vecino más cercano sobre el
centroide predicho con un modelo de velocidad constante) y, al ser puro Python,
es el único que se puede probar de forma determinista en CI.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

BBox = Sequence[float]
TrackedBox = Tuple[int, float, float, float, float]


def bbox_center(bbox: BBox) -> Tuple[float, float]:
    return (float(bbox[0]) + float(bbox[2])) / 2.0, (float(bbox[1]) + float(bbox[3])) / 2.0


class _Track:
    __slots__ = ("track_id", "cx", "cy", "vx", "vy", "bbox", "missing", "hits")

    def __init__(self, track_id: int, bbox: BBox):
        self.track_id = track_id
        self.cx, self.cy = bbox_center(bbox)
        self.vx = 0.0
        self.vy = 0.0
        self.bbox = tuple(float(v) for v in bbox)
        self.missing = 0
        self.hits = 1

    @property
    def predicted(self) -> Tuple[float, float]:
        return self.cx + self.vx, self.cy + self.vy

    def observe(self, bbox: BBox, smoothing: float) -> None:
        cx, cy = bbox_center(bbox)
        self.vx = smoothing * (cx - self.cx) + (1.0 - smoothing) * self.vx
        self.vy = smoothing * (cy - self.cy) + (1.0 - smoothing) * self.vy
        self.cx, self.cy = cx, cy
        self.bbox = tuple(float(v) for v in bbox)
        self.missing = 0
        self.hits += 1

    def coast(self) -> None:
        self.cx, self.cy = self.predicted
        self.missing += 1


class SimpleCentroidTracker:
    """Asocia detecciones a tracks por distancia al centroide predicho."""

    def __init__(
        self,
        distance_threshold: float = 50.0,
        max_missing: int = 20,
        min_hits: int = 2,
        velocity_smoothing: float = 0.5,
    ):
        if distance_threshold <= 0:
            raise ValueError("distance_threshold debe ser > 0")
        if max_missing < 0:
            raise ValueError("max_missing debe ser >= 0")
        self.distance_threshold = float(distance_threshold)
        self.max_missing = int(max_missing)
        self.min_hits = max(1, int(min_hits))
        self.velocity_smoothing = float(velocity_smoothing)
        self._tracks: Dict[int, _Track] = {}
        self._next_id = 1

    @property
    def active_tracks(self) -> int:
        return len(self._tracks)

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1

    def update(self, boxes: Sequence[BBox], scores: Optional[Sequence[float]] = None) -> List[TrackedBox]:
        """Procesa las detecciones de un frame y devuelve ``(id, x1, y1, x2, y2)``."""
        detections = [tuple(float(v) for v in box) for box in boxes]
        confidences = list(scores) if scores is not None else [1.0] * len(detections)

        # Pares candidatos ordenados por distancia: asignación voraz, que para
        # ~22 jugadores es indistinguible del húngaro y mucho más simple.
        pairs: List[Tuple[float, int, int]] = []
        track_ids = list(self._tracks.keys())
        for tid in track_ids:
            px, py = self._tracks[tid].predicted
            for di, det in enumerate(detections):
                dcx, dcy = bbox_center(det)
                dist = ((px - dcx) ** 2 + (py - dcy) ** 2) ** 0.5
                if dist <= self.distance_threshold:
                    pairs.append((dist, tid, di))
        pairs.sort(key=lambda item: (item[0], item[1], item[2]))

        used_tracks: set = set()
        used_dets: set = set()
        for _, tid, di in pairs:
            if tid in used_tracks or di in used_dets:
                continue
            self._tracks[tid].observe(detections[di], self.velocity_smoothing)
            used_tracks.add(tid)
            used_dets.add(di)

        for tid in track_ids:
            if tid not in used_tracks:
                self._tracks[tid].coast()

        # Detecciones sin track: nuevas identidades, las más confiables primero.
        unmatched = sorted(
            (di for di in range(len(detections)) if di not in used_dets),
            key=lambda di: -float(confidences[di]) if di < len(confidences) else 0.0,
        )
        for di in unmatched:
            track = _Track(self._next_id, detections[di])
            self._tracks[self._next_id] = track
            self._next_id += 1

        for tid in [tid for tid, track in self._tracks.items() if track.missing > self.max_missing]:
            del self._tracks[tid]

        return [
            (track.track_id, *track.bbox)
            for track in sorted(self._tracks.values(), key=lambda t: t.track_id)
            if track.missing == 0 and track.hits >= self.min_hits
        ]
