"""Configuración por defecto y validación del runtime de análisis."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

# ── Constantes de dominio ────────────────────────────────────────────────
PERSON_CLASS = 0        # COCO: person
BALL_CLASS = 32         # COCO: sports ball

FIELD_W_METERS = 105.0  # largo del campo (eje x del mundo)
FIELD_H_METERS = 68.0   # ancho del campo (eje y del mundo)

ALLOWED_TRACKERS: frozenset = frozenset({"bytetrack", "norfair", "simple"})
ALLOWED_DET_MODES: frozenset = frozenset({"normal", "sahi"})
ALLOWED_TEAM_CLFS: frozenset = frozenset({"kmeans", "grass_kmeans", "osnet"})
ALLOWED_MANUAL_TEAMS: frozenset = frozenset({"team_1", "team_2", "unknown"})

#: Valores por defecto del runtime. Cualquier clave fuera de este diccionario
#: se rechaza en :func:`merge_config`, lo que evita que un payload arbitrario
#: contamine la configuración de una sesión.
DEFAULTS: Dict[str, Any] = {
    "model_path": "yolo11x.pt",
    "imgsz": 1280,
    "confidence": 0.10,
    "iou": 0.45,
    "agnostic_nms": False,
    "augment": False,
    "detection_mode": "sahi",
    "sahi_slice": 320,
    "sahi_overlap": 0.2,
    "tracker_type": "norfair",
    "norfair_dist": 50,
    "norfair_hit_max": 20,
    "team_classifier": "grass_kmeans",
    "osnet_weight_path": "weights/osnet_x1_0_imagenet.pth",
    "frame_skip": 2,
    "process_width": 854,
    "process_height": 480,
}

#: Rango admitido para las claves numéricas: clave → (mínimo, máximo, tipo).
_NUMERIC_BOUNDS: Dict[str, Tuple[float, float, type]] = {
    "imgsz": (320, 2048, int),
    "confidence": (0.0, 1.0, float),
    "iou": (0.0, 1.0, float),
    "sahi_slice": (128, 1024, int),
    "sahi_overlap": (0.0, 0.5, float),
    "norfair_dist": (5, 300, int),
    "norfair_hit_max": (1, 240, int),
    "frame_skip": (0, 30, int),
    "process_width": (320, 1920, int),
    "process_height": (180, 1080, int),
}

_ENUM_FIELDS: Dict[str, Iterable[str]] = {
    "detection_mode": ALLOWED_DET_MODES,
    "tracker_type": ALLOWED_TRACKERS,
    "team_classifier": ALLOWED_TEAM_CLFS,
}

_BOOL_FIELDS = ("agnostic_nms", "augment")


class ConfigError(ValueError):
    """Configuración inválida — el llamador la traduce a HTTP 400."""


def default_runtime_config() -> Dict[str, Any]:
    """Copia fresca de la configuración por defecto."""
    return dict(DEFAULTS)


def _coerce_numeric(key: str, value: Any) -> Any:
    low, high, caster = _NUMERIC_BOUNDS[key]
    if isinstance(value, bool):
        raise ConfigError(f"{key}: se esperaba un número")
    try:
        casted = caster(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key}: se esperaba un número") from exc
    if not low <= casted <= high:
        raise ConfigError(f"{key}: fuera de rango [{low}, {high}]")
    return casted


def validate_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Valida y normaliza un parche de configuración.

    Devuelve sólo las claves presentes en *patch*, ya convertidas al tipo
    correcto. Lanza :class:`ConfigError` ante claves desconocidas o valores
    fuera de rango.
    """
    clean: Dict[str, Any] = {}
    for key, value in patch.items():
        if value is None:
            continue
        if key not in DEFAULTS:
            raise ConfigError(f"clave de configuracion desconocida: {key}")
        if key in _NUMERIC_BOUNDS:
            clean[key] = _coerce_numeric(key, value)
        elif key in _ENUM_FIELDS:
            if value not in _ENUM_FIELDS[key]:
                allowed = ", ".join(sorted(_ENUM_FIELDS[key]))
                raise ConfigError(f"{key}: valor invalido (permitidos: {allowed})")
            clean[key] = value
        elif key in _BOOL_FIELDS:
            clean[key] = bool(value)
        else:
            clean[key] = str(value)
    return clean


def merge_config(base: Optional[Dict[str, Any]], patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fusiona *patch* sobre *base* (o sobre los defaults) tras validarlo."""
    merged = default_runtime_config()
    if base:
        merged.update(validate_config({k: v for k, v in base.items() if k in DEFAULTS}))
    if patch:
        merged.update(validate_config(patch))
    return merged
