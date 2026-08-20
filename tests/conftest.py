"""Fixtures compartidas: modelo YOLO falso, analizador y cliente HTTP.

Los tests no descargan pesos ni ejecutan una red neuronal: se inyecta un
detector guionizado en el registro compartido, así que toda la suite corre en
segundos y es determinista.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fcopilot.config import BALL_CLASS, PERSON_CLASS  # noqa: E402
from fcopilot.detection import shared_yolo_registry  # noqa: E402

Box = Tuple[Sequence[float], float, int]


class _FakeTensor:
    """Imita lo justo de un tensor de ultralytics: ``.cpu().numpy()``."""

    def __init__(self, value):
        self._value = np.asarray(value, dtype=float)

    def cpu(self):
        return self

    def numpy(self):
        return self._value

    def __float__(self):
        return float(self._value)

    def __int__(self):
        return int(self._value)


class _FakeBox:
    def __init__(self, xyxy: Sequence[float], conf: float, cls: int):
        self.xyxy = [_FakeTensor(xyxy)]
        self.conf = [_FakeTensor(conf)]
        self.cls = [_FakeTensor(cls)]


class _FakeResult:
    def __init__(self, boxes: Iterable[_FakeBox]):
        self.boxes = list(boxes)


class FakeYOLO:
    """Devuelve las cajas que le indique el test, frame a frame."""

    def __init__(self, script: List[List[Box]] | None = None):
        self.script: List[List[Box]] = script or []
        self.calls = 0
        self.last_kwargs: dict = {}

    def set_script(self, script: List[List[Box]]) -> None:
        self.script = script
        self.calls = 0

    def predict(self, frame, **kwargs):
        self.last_kwargs = kwargs
        boxes = self.script[self.calls] if self.calls < len(self.script) else (self.script[-1] if self.script else [])
        self.calls += 1
        return [_FakeResult(_FakeBox(*b) for b in boxes)]


def players_row(count: int, y: float = 100.0, x0: float = 50.0, step: float = 60.0, dx: float = 0.0) -> List[Box]:
    """Una fila de jugadores separados ``step`` px, desplazada ``dx``."""
    return [((x0 + i * step + dx, y, x0 + i * step + dx + 24, y + 60), 0.9, PERSON_CLASS) for i in range(count)]


def ball_box(x: float, y: float, conf: float = 0.6) -> Box:
    return ((x, y, x + 12, y + 12), conf, BALL_CLASS)


@pytest.fixture
def fake_yolo() -> FakeYOLO:
    """Registra el modelo falso bajo la ruta por defecto de la configuración."""
    model = FakeYOLO()
    shared_yolo_registry.clear()
    shared_yolo_registry.register("yolo11x.pt", model)
    yield model
    shared_yolo_registry.clear()


@pytest.fixture
def analyzer(fake_yolo):
    from fcopilot.analyzer import FootballAnalyzer

    return FootballAnalyzer({"tracker_type": "simple", "detection_mode": "normal", "team_classifier": "kmeans"})


@pytest.fixture
def green_frame() -> np.ndarray:
    """Frame sintético: césped verde con dos bloques de camisetas distintas."""
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    frame[:, :] = (40, 140, 40)  # BGR: verde césped
    return frame


@pytest.fixture
def client(tmp_path, fake_yolo, monkeypatch):
    """``TestClient`` con estado de sesión aislado en un directorio temporal."""
    from fastapi.testclient import TestClient

    import football_copilot_v2_backend as backend
    from fcopilot.analyzer import FootballAnalyzer
    from fcopilot.sessions import SessionManager

    manager = SessionManager(
        state_dir=tmp_path / "state",
        ttl_seconds=1800,
        max_sessions=3,
        analyzer_factory=lambda: FootballAnalyzer(
            {"tracker_type": "simple", "detection_mode": "normal", "team_classifier": "kmeans"}
        ),
    )
    monkeypatch.setattr(backend, "session_manager", manager)
    monkeypatch.setattr(backend, "MODEL_ROOT", ROOT)
    with TestClient(backend.app) as test_client:
        test_client.session_manager = manager
        yield test_client
