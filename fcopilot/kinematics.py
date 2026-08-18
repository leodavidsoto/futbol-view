"""Cinemática por jugador: distancia, velocidad, sprints y zonas de esfuerzo.

Puntos clave del diseño (y errores que corrige respecto de la versión previa):

* **Base de tiempo real.** La velocidad se calcula con el instante de cada
  muestra (tiempo de vídeo o reloj de la cámara), no con los FPS de procesado.
  Analizar 1 de cada 3 frames ya no multiplica por tres las velocidades.
* **Distancia sin doble conteo.** Cada tramo se acumula una sola vez, entre la
  muestra nueva y la inmediatamente anterior.
* **Rechazo de saltos imposibles.** Un cambio de identidad del tracker producía
  un "teletransporte" que inflaba la distancia; los tramos por encima de
  ``max_speed_kmh`` se descartan.
* **Métricas de rendimiento.** Velocidad punta, media, sprints y distancia por
  zona de intensidad, que es lo que se mira en un informe de partido.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

#: Base de tiempo de una muestra. ``video`` es el único valor con el que las
#: métricas significan lo que dicen; ``reloj`` sólo es legítimo en directo
#: (webcam), donde no existe un tiempo de vídeo que consultar.
TIME_SOURCE_VIDEO = "video"
TIME_SOURCE_CLOCK = "reloj"
TIME_SOURCES = (TIME_SOURCE_VIDEO, TIME_SOURCE_CLOCK)


class TimeBaseError(ValueError):
    """La base de tiempo de una muestra es incoherente con las anteriores.

    Es la regla 5 de ``AGENTS.md`` hecha código. Se lanza cuando el tiempo
    retrocede o cuando se mezclan dos fuentes de tiempo dentro del mismo
    análisis: las dos cosas producen métricas que parecen correctas y no lo son,
    que es exactamente el fallo que ya pasó desapercibido una vez.
    """


#: Zonas de intensidad (nombre, km/h mínimo inclusive, km/h máximo exclusive).
SPEED_ZONES: Tuple[Tuple[str, float, float], ...] = (
    ("caminando", 0.0, 7.0),
    ("trote", 7.0, 14.0),
    ("carrera", 14.0, 20.0),
    ("alta_intensidad", 20.0, 25.0),
    ("sprint", 25.0, math.inf),
)


@dataclass(frozen=True)
class Sample:
    """Una posición observada de un jugador."""

    frame: int
    t: float
    x: float
    y: float
    wx: Optional[float] = None
    wy: Optional[float] = None

    @property
    def has_world(self) -> bool:
        return self.wx is not None and self.wy is not None

    def as_dict(self) -> Dict[str, float]:
        data: Dict[str, float] = {"frame": self.frame, "t": round(self.t, 3), "x": self.x, "y": self.y}
        if self.has_world:
            data["wx"] = round(float(self.wx), 2)
            data["wy"] = round(float(self.wy), 2)
        return data


@dataclass
class KinematicsConfig:
    """Parámetros de cálculo. ``pixels_per_meter`` sólo se usa sin homografía."""

    pixels_per_meter: float = 8.0
    max_speed_kmh: float = 45.0
    speed_window_s: float = 0.5
    smoothing: float = 0.5
    sprint_kmh: float = 25.0
    min_sprint_s: float = 0.7
    max_history: int = 300

    def __post_init__(self) -> None:
        if self.pixels_per_meter <= 0:
            raise ValueError("pixels_per_meter debe ser > 0")
        if not 0.0 <= self.smoothing <= 1.0:
            raise ValueError("smoothing debe estar en [0, 1]")
        if self.speed_window_s <= 0:
            raise ValueError("speed_window_s debe ser > 0")


def zone_for_speed(speed_kmh: float) -> str:
    """Zona de intensidad a la que pertenece una velocidad."""
    for name, low, high in SPEED_ZONES:
        if low <= speed_kmh < high:
            return name
    return SPEED_ZONES[-1][0]


class PlayerKinematics:
    """Estado cinemático acumulado de un track."""

    def __init__(self, track_id: int, config: Optional[KinematicsConfig] = None):
        self.track_id = track_id
        self.config = config or KinematicsConfig()
        self.samples: List[Sample] = []
        self.total_distance_m = 0.0
        self.speed_kmh = 0.0
        self.max_speed_kmh = 0.0
        self.zone_distance_m: Dict[str, float] = {name: 0.0 for name, _, _ in SPEED_ZONES}
        self.sprints = 0
        self.rejected_steps = 0
        self.duplicate_samples = 0
        self.active_seconds = 0.0
        self._sprint_elapsed = 0.0
        self._first_t: Optional[float] = None
        self._last_t: Optional[float] = None

    # ── Conversión a metros ────────────────────────────────────────────
    def _metric_point(self, sample: Sample) -> Tuple[float, float]:
        """Posición en metros: mundo si hay homografía, si no píxeles escalados."""
        if sample.has_world:
            return float(sample.wx), float(sample.wy)
        ppm = self.config.pixels_per_meter
        return sample.x / ppm, sample.y / ppm

    def _distance_m(self, a: Sample, b: Sample) -> float:
        # Si una muestra tiene mundo y la otra no, la comparación sería entre
        # sistemas de coordenadas distintos: se mide en píxeles para ambas.
        if a.has_world != b.has_world:
            ppm = self.config.pixels_per_meter
            return math.hypot(b.x - a.x, b.y - a.y) / ppm
        ax, ay = self._metric_point(a)
        bx, by = self._metric_point(b)
        return math.hypot(bx - ax, by - ay)

    # ── Actualización ──────────────────────────────────────────────────
    def update(self, sample: Sample) -> float:
        """Registra una muestra y devuelve la velocidad suavizada en km/h.

        Lanza :class:`TimeBaseError` si el tiempo retrocede. Una muestra con el
        mismo ``t`` que la anterior no es un error —un vídeo puede repetir
        marca de tiempo— pero no aporta desplazamiento, así que se descarta y se
        cuenta en ``duplicate_samples`` en vez de dividir por cero.
        """
        previous = self.samples[-1] if self.samples else None
        if previous is not None:
            if sample.t < previous.t:
                raise TimeBaseError(
                    f"track {self.track_id}: el tiempo retrocede de {previous.t:.3f}s a "
                    f"{sample.t:.3f}s. Las métricas se calculan sobre tiempo de vídeo "
                    f"monótono; revisa de dónde sale el timestamp."
                )
            if sample.t == previous.t:
                self.duplicate_samples += 1
                return self.speed_kmh
        self.samples.append(sample)
        if len(self.samples) > self.config.max_history:
            del self.samples[: len(self.samples) - self.config.max_history]

        if self._first_t is None:
            self._first_t = sample.t
        self._last_t = sample.t

        if previous is not None:
            dt = sample.t - previous.t
            if dt > 0:
                step_m = self._distance_m(previous, sample)
                step_kmh = step_m / dt * 3.6
                if step_kmh > self.config.max_speed_kmh:
                    # Salto imposible: casi siempre un cambio de identidad del
                    # tracker. No se acumula, pero se contabiliza para poder
                    # diagnosticar la calidad del tracking.
                    self.rejected_steps += 1
                else:
                    self.total_distance_m += step_m
                    self.zone_distance_m[zone_for_speed(step_kmh)] += step_m
                    self.active_seconds += dt

        self.speed_kmh = self._compute_speed()
        self.max_speed_kmh = max(self.max_speed_kmh, self.speed_kmh)
        self._update_sprints(sample, previous)
        return self.speed_kmh

    def _compute_speed(self) -> float:
        """Velocidad sobre una ventana temporal, suavizada con un EMA."""
        if len(self.samples) < 2:
            return 0.0
        latest = self.samples[-1]
        window_start = latest.t - self.config.speed_window_s
        anchor = self.samples[0]
        for sample in reversed(self.samples[:-1]):
            anchor = sample
            if sample.t <= window_start:
                break
        dt = latest.t - anchor.t
        if dt <= 0:
            return self.speed_kmh
        raw = self._distance_m(anchor, latest) / dt * 3.6
        if raw > self.config.max_speed_kmh:
            raw = self.speed_kmh
        alpha = self.config.smoothing
        return round(alpha * raw + (1.0 - alpha) * self.speed_kmh, 2)

    def _update_sprints(self, sample: Sample, previous: Optional[Sample]) -> None:
        if previous is None:
            return
        dt = max(sample.t - previous.t, 0.0)
        if self.speed_kmh >= self.config.sprint_kmh:
            self._sprint_elapsed += dt
            return
        if self._sprint_elapsed >= self.config.min_sprint_s:
            self.sprints += 1
        self._sprint_elapsed = 0.0

    def finalize(self) -> None:
        """Cierra un sprint en curso al terminar el análisis."""
        if self._sprint_elapsed >= self.config.min_sprint_s:
            self.sprints += 1
        self._sprint_elapsed = 0.0

    # ── Lectura ────────────────────────────────────────────────────────
    @property
    def avg_speed_kmh(self) -> float:
        if self.active_seconds <= 0:
            return 0.0
        return round(self.total_distance_m / self.active_seconds * 3.6, 2)

    @property
    def observed_seconds(self) -> float:
        if self._first_t is None or self._last_t is None:
            return 0.0
        return round(self._last_t - self._first_t, 2)

    def trail(self, length: int = 20) -> List[Dict[str, float]]:
        return [s.as_dict() for s in self.samples[-length:]]

    def summary(self) -> Dict[str, object]:
        return {
            "track_id": self.track_id,
            "total_dist_m": round(self.total_distance_m, 1),
            "speed_kmh": round(self.speed_kmh, 1),
            "max_speed_kmh": round(self.max_speed_kmh, 1),
            "avg_speed_kmh": self.avg_speed_kmh,
            "sprints": self.sprints,
            "observed_s": self.observed_seconds,
            "rejected_steps": self.rejected_steps,
            "duplicate_samples": self.duplicate_samples,
            "zones_m": {k: round(v, 1) for k, v in self.zone_distance_m.items()},
        }

    # ── Serialización (persistencia de sesión) ─────────────────────────
    def to_state(self) -> Dict[str, object]:
        return {
            "track_id": self.track_id,
            "samples": [s.as_dict() for s in self.samples],
            "total_distance_m": self.total_distance_m,
            "speed_kmh": self.speed_kmh,
            "max_speed_kmh": self.max_speed_kmh,
            "zone_distance_m": dict(self.zone_distance_m),
            "sprints": self.sprints,
            "rejected_steps": self.rejected_steps,
            "duplicate_samples": self.duplicate_samples,
            "active_seconds": self.active_seconds,
            "first_t": self._first_t,
            "last_t": self._last_t,
        }

    @classmethod
    def from_state(cls, state: Dict[str, object], config: Optional[KinematicsConfig] = None) -> "PlayerKinematics":
        obj = cls(int(state.get("track_id", 0)), config)
        for raw in state.get("samples", []) or []:
            obj.samples.append(
                Sample(
                    frame=int(raw.get("frame", 0)),
                    t=float(raw.get("t", 0.0)),
                    x=float(raw.get("x", 0.0)),
                    y=float(raw.get("y", 0.0)),
                    wx=float(raw["wx"]) if raw.get("wx") is not None else None,
                    wy=float(raw["wy"]) if raw.get("wy") is not None else None,
                )
            )
        obj.total_distance_m = float(state.get("total_distance_m", 0.0))
        obj.speed_kmh = float(state.get("speed_kmh", 0.0))
        obj.max_speed_kmh = float(state.get("max_speed_kmh", 0.0))
        zones = state.get("zone_distance_m") or {}
        for name, _, _ in SPEED_ZONES:
            obj.zone_distance_m[name] = float(zones.get(name, 0.0))
        obj.sprints = int(state.get("sprints", 0))
        obj.rejected_steps = int(state.get("rejected_steps", 0))
        obj.duplicate_samples = int(state.get("duplicate_samples", 0))
        obj.active_seconds = float(state.get("active_seconds", 0.0))
        obj._first_t = state.get("first_t")
        obj._last_t = state.get("last_t")
        return obj
