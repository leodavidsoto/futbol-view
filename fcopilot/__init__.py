"""
fcopilot — núcleo analítico de Football Copilot.

Este paquete contiene la lógica de análisis *pura* (sin FastAPI, sin YOLO y sin
PyTorch) para que pueda probarse en milisegundos y reutilizarse fuera del
servidor: geometría de campo, cinemática de jugadores, posesión, un tracker de
respaldo sin dependencias y la construcción del informe del partido.

El backend (`football_copilot_v2_backend.py`) es una capa fina sobre estos
módulos: detecta, trackea y delega todas las métricas aquí.
"""

from fcopilot.config import (
    ALLOWED_DET_MODES,
    ALLOWED_MANUAL_TEAMS,
    ALLOWED_TEAM_CLFS,
    ALLOWED_TRACKERS,
    DEFAULTS,
    default_runtime_config,
    merge_config,
)
from fcopilot.geometry import (
    find_homography,
    perspective_transform_point,
    quad_is_degenerate,
)
from fcopilot.kinematics import (
    SPEED_ZONES,
    TIME_SOURCE_CLOCK,
    TIME_SOURCE_VIDEO,
    TIME_SOURCES,
    KinematicsConfig,
    PlayerKinematics,
    Sample,
    TimeBaseError,
)
from fcopilot.possession import PossessionTracker
from fcopilot.report import build_report
from fcopilot.teams import ColorTeamClassifier, GrassAwareTeamClassifier
from fcopilot.tracking import SimpleCentroidTracker

__all__ = [
    "ALLOWED_DET_MODES",
    "ALLOWED_MANUAL_TEAMS",
    "ALLOWED_TEAM_CLFS",
    "ALLOWED_TRACKERS",
    "ColorTeamClassifier",
    "DEFAULTS",
    "GrassAwareTeamClassifier",
    "KinematicsConfig",
    "PlayerKinematics",
    "PossessionTracker",
    "SPEED_ZONES",
    "Sample",
    "TIME_SOURCES",
    "TIME_SOURCE_CLOCK",
    "TIME_SOURCE_VIDEO",
    "TimeBaseError",
    "SimpleCentroidTracker",
    "build_report",
    "default_runtime_config",
    "find_homography",
    "merge_config",
    "perspective_transform_point",
    "quad_is_degenerate",
]

__version__ = "3.0.0"
