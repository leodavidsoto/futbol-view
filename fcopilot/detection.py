"""Detección de jugadores y balón (YOLO, opcionalmente con SAHI).

``ultralytics`` y ``sahi`` son dependencias opcionales: el módulo importa sin
ellas y el error se reporta al usar el detector, no al arrancar el servidor.
Eso permite ejecutar la API y toda la suite de tests en un entorno ligero.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Dict, List, Sequence, Tuple

import numpy as np

from fcopilot.config import BALL_CLASS, PERSON_CLASS

logger = logging.getLogger("fcopilot.detection")

try:
    from ultralytics import YOLO

    YOLO_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin ultralytics
    YOLO = None  # type: ignore[assignment]
    YOLO_AVAILABLE = False

try:
    from sahi import AutoDetectionModel
    from sahi.predict import get_sliced_prediction

    SAHI_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin sahi
    AutoDetectionModel = None  # type: ignore[assignment]
    get_sliced_prediction = None  # type: ignore[assignment]
    SAHI_AVAILABLE = False

#: ``(person_xyxy, person_conf, ball_candidates)``
DetectionResult = Tuple[List[np.ndarray], List[float], List[Tuple[np.ndarray, float]]]


class DetectorUnavailable(RuntimeError):
    """No hay backend de detección instalado."""


class SharedYOLORegistry:
    """Un único modelo YOLO por ruta, compartido entre todas las sesiones."""

    def __init__(self):
        self._lock = threading.RLock()
        self._models: Dict[str, object] = {}

    def register(self, model_path: str, model: object) -> None:
        """Inyecta un modelo ya construido (usado por los tests)."""
        with self._lock:
            self._models[os.path.abspath(model_path)] = model

    def get(self, model_path: str):
        abs_path = os.path.abspath(model_path)
        with self._lock:
            model = self._models.get(abs_path)
            if model is not None:
                return model
            if not YOLO_AVAILABLE:
                raise DetectorUnavailable(
                    "ultralytics no esta instalado: pip install -r requirements_v2.txt"
                )
            logger.info("Cargando YOLO compartido: %s", abs_path)
            model = YOLO(abs_path)
            model.predict(np.zeros((64, 64, 3), dtype=np.uint8), verbose=False)
            self._models[abs_path] = model
            return model

    def clear(self) -> None:
        with self._lock:
            self._models.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"shared_yolo_models": len(self._models)}


shared_yolo_registry = SharedYOLORegistry()


def split_by_class(
    boxes: Sequence[Tuple[Sequence[float], float, int]],
    person_class: int = PERSON_CLASS,
    ball_class: int = BALL_CLASS,
) -> DetectionResult:
    """Reparte ``(xyxy, conf, clase)`` en personas y candidatos a balón.

    Los índices son parámetros porque no todos los modelos usan los de COCO: uno
    entrenado para fútbol suele traer `ball`, `player`, `referee`, `goalkeeper`
    con sus propios números.
    """
    person_xyxy: List[np.ndarray] = []
    person_conf: List[float] = []
    ball: List[Tuple[np.ndarray, float]] = []
    for xyxy, conf, cls in boxes:
        arr = np.asarray(xyxy, dtype=float)
        if int(cls) == person_class:
            person_xyxy.append(arr)
            person_conf.append(float(conf))
        elif int(cls) == ball_class:
            ball.append((arr, float(conf)))
    return person_xyxy, person_conf, ball


class Detector:
    """Envuelve el modelo YOLO y, si procede, la inferencia por tiles de SAHI."""

    def __init__(self, config: Dict[str, object]):
        self.config = config
        self.model_path = str(config["model_path"])
        self.model = shared_yolo_registry.get(self.model_path)
        self.sahi_model = None
        self._init_sahi()

    # Los índices se leen **en vivo** de la configuración, como el resto de
    # parámetros. Guardarlos en el constructor los congelaba: al cambiar de
    # modelo desde la API, `apply_config` actualizaba el diccionario pero el
    # detector seguía filtrando por las clases del modelo anterior, así que
    # devolvía casi nada y el fallo no se parecía en nada a su causa.
    @property
    def person_class(self) -> int:
        return int(self.config.get("person_class", PERSON_CLASS))

    @property
    def ball_class(self) -> int:
        return int(self.config.get("ball_class", BALL_CLASS))

    def _init_sahi(self) -> None:
        self.sahi_model = None
        if not SAHI_AVAILABLE or not YOLO_AVAILABLE:
            return
        try:
            self.sahi_model = AutoDetectionModel.from_pretrained(
                model_type="ultralytics",
                model_path=self.model_path,
                confidence_threshold=float(self.config["confidence"]),
                device="cpu",
            )
            logger.info("SAHI inicializado (%s)", self.model_path)
        except Exception as exc:  # pragma: no cover - depende del entorno
            logger.warning("SAHI init error: %s", exc)

    def reload(self, model_path: str) -> None:
        logger.info("Recargando modelo: %s", model_path)
        self.model = shared_yolo_registry.get(model_path)
        self.model_path = model_path
        self._init_sahi()

    @property
    def sahi_ready(self) -> bool:
        return self.sahi_model is not None

    # ── Inferencia ─────────────────────────────────────────────────────
    def predict(self, frame: np.ndarray) -> DetectionResult:
        if self.config.get("detection_mode") == "sahi" and self.sahi_ready:
            return self.predict_sahi(frame)
        return self.predict_normal(frame)

    def predict_normal(self, frame: np.ndarray) -> DetectionResult:
        results = self.model.predict(
            frame,
            conf=float(self.config["confidence"]),
            iou=float(self.config["iou"]),
            classes=[self.person_class, self.ball_class],
            imgsz=int(self.config["imgsz"]),
            augment=bool(self.config["augment"]),
            agnostic_nms=bool(self.config["agnostic_nms"]),
            verbose=False,
        )[0]
        boxes = [
            (box.xyxy[0].cpu().numpy(), float(box.conf[0]), int(box.cls[0]))
            for box in results.boxes
        ]
        return split_by_class(boxes, self.person_class, self.ball_class)

    def predict_sahi(self, frame: np.ndarray) -> DetectionResult:
        if not self.sahi_ready:
            return self.predict_normal(frame)
        self.sahi_model.confidence_threshold = float(self.config["confidence"])
        result = get_sliced_prediction(
            frame,
            self.sahi_model,
            slice_height=int(self.config["sahi_slice"]),
            slice_width=int(self.config["sahi_slice"]),
            overlap_height_ratio=float(self.config["sahi_overlap"]),
            overlap_width_ratio=float(self.config["sahi_overlap"]),
            perform_standard_pred=True,
            postprocess_class_agnostic=bool(self.config["agnostic_nms"]),
            verbose=0,
        )
        boxes = [
            (
                (pred.bbox.minx, pred.bbox.miny, pred.bbox.maxx, pred.bbox.maxy),
                float(pred.score.value),
                int(pred.category.id),
            )
            for pred in result.object_prediction_list
        ]
        return split_by_class(boxes, self.person_class, self.ball_class)
