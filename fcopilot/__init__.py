"""
fcopilot — núcleo analítico de Football Copilot.

Este paquete contiene la lógica de análisis *pura* (sin FastAPI, sin YOLO y sin
PyTorch) para que pueda probarse en milisegundos y reutilizarse fuera del
servidor: geometría de campo, cinemática de jugadores, posesión, un tracker de
respaldo sin dependencias y la construcción del informe del partido.

El backend (`football_copilot_v2_backend.py`) es una capa fina sobre estos
módulos: detecta, trackea y delega todas las métricas aquí.
"""

from fcopilot.collective import (
    CORRIDORS,
    THIRDS,
    CollectiveError,
    Occupancy,
    ShapeSeries,
    ZoneGrid,
    line_summary,
    team_shape,
)
from fcopilot.config import (
    ALLOWED_DET_MODES,
    ALLOWED_MANUAL_TEAMS,
    ALLOWED_TEAM_CLFS,
    ALLOWED_TRACKERS,
    DEFAULTS,
    default_runtime_config,
    merge_config,
)
from fcopilot.dashboard import DashboardConfig, Quality, build_dashboard
from fcopilot.geometry import (
    find_homography,
    perspective_transform_point,
    quad_is_degenerate,
)
from fcopilot.load import (
    ACCEL_THRESHOLD_MS2,
    HIGH_INTENSITY_KMH,
    SPEED_BANDS,
    SPRINT_KMH,
    ExternalLoad,
    LoadConfig,
    SquadLoad,
    band_for_speed,
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
from fcopilot.pitch import (
    DEFAULT_PITCH,
    PITCHES,
    PitchError,
    PitchSpec,
    get_pitch,
    homography_from_landmarks,
    landmarks_for_calibration,
    scaled_pitch,
)
from fcopilot.possession import PossessionTracker
from fcopilot.report import build_report
from fcopilot.teams import ColorTeamClassifier, GrassAwareTeamClassifier
from fcopilot.tracking import SimpleCentroidTracker

__all__ = [
    "ACCEL_THRESHOLD_MS2",
    "ALLOWED_DET_MODES",
    "ALLOWED_MANUAL_TEAMS",
    "ALLOWED_TEAM_CLFS",
    "ALLOWED_TRACKERS",
    "band_for_speed",
    "build_dashboard",
    "build_report",
    "CollectiveError",
    "ColorTeamClassifier",
    "CORRIDORS",
    "DashboardConfig",
    "DEFAULT_PITCH",
    "default_runtime_config",
    "DEFAULTS",
    "ExternalLoad",
    "find_homography",
    "get_pitch",
    "GrassAwareTeamClassifier",
    "HIGH_INTENSITY_KMH",
    "homography_from_landmarks",
    "KinematicsConfig",
    "landmarks_for_calibration",
    "line_summary",
    "LoadConfig",
    "merge_config",
    "Occupancy",
    "perspective_transform_point",
    "PitchError",
    "PITCHES",
    "PitchSpec",
    "PlayerKinematics",
    "PossessionTracker",
    "quad_is_degenerate",
    "Quality",
    "Sample",
    "scaled_pitch",
    "ShapeSeries",
    "SimpleCentroidTracker",
    "SPEED_BANDS",
    "SPEED_ZONES",
    "SPRINT_KMH",
    "SquadLoad",
    "team_shape",
    "THIRDS",
    "TIME_SOURCE_CLOCK",
    "TIME_SOURCE_VIDEO",
    "TIME_SOURCES",
    "TimeBaseError",
    "ZoneGrid",
]

__version__ = "3.0.0"
