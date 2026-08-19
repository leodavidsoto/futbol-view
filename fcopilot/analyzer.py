"""Analizador de partido: detección → tracking → equipos → métricas.

Es la única clase con estado del sistema. Se apoya en:

* :mod:`fcopilot.detection` para YOLO/SAHI,
* Norfair, ByteTrack o :class:`~fcopilot.tracking.SimpleCentroidTracker`,
* :mod:`fcopilot.teams` / :mod:`fcopilot.osnet` para la clasificación de equipos,
* :mod:`fcopilot.kinematics` y :mod:`fcopilot.possession` para las métricas.

Todo el trabajo por frame se hace bajo ``state_lock``; el resto de la clase
(sesiones, serialización) usa ``session_lock`` para no bloquear el análisis.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from fcopilot.config import default_runtime_config, merge_config
from fcopilot.detection import Detector
from fcopilot.geometry import (
    find_homography,
    perspective_transform_point,
    point_in_polygon,
    validate_play_area,
)
from fcopilot.kinematics import (
    TIME_SOURCE_CLOCK,
    TIME_SOURCE_VIDEO,
    KinematicsConfig,
    PlayerKinematics,
    Sample,
    TimeBaseError,
)
from fcopilot.osnet import OSNetTeamClassifier
from fcopilot.dashboard import DashboardConfig, Quality, build_dashboard
from fcopilot.pitch import DEFAULT_PITCH, PITCHES, PitchSpec, get_pitch, homography_from_landmarks
from fcopilot.possession import PossessionTracker
from fcopilot.report import build_report
from fcopilot.teams import ColorTeamClassifier, GrassAwareTeamClassifier
from fcopilot.tracking import SimpleCentroidTracker
from fcopilot.tracklets import MergeConfig, Tracklet, merge_tracklets

logger = logging.getLogger("fcopilot.analyzer")

#: Distancia máxima jugador-balón para adjudicar posesión.
POSSESSION_DIST_PX = 90.0
POSSESSION_DIST_M = 3.0
FPS_TARGET = 20
MAX_TRACK_HISTORY = 300

try:
    from norfair import Detection as NorfairDetection, Tracker as NorfairTracker

    NORFAIR_AVAILABLE = True
except ImportError:  # pragma: no cover
    NORFAIR_AVAILABLE = False

try:
    import supervision as sv

    BYTETRACK_AVAILABLE = True
except ImportError:  # pragma: no cover
    sv = None  # type: ignore[assignment]
    BYTETRACK_AVAILABLE = False


def make_team_classifier(clf_type: str, osnet_weight_path: str):
    """Crea el clasificador de equipos, degradando si el pedido no está listo."""
    if clf_type == "osnet":
        clf = OSNetTeamClassifier(osnet_weight_path)
        if clf.available:
            logger.info("Clasificador de equipos: OSNet (apariencia)")
            return clf
        logger.warning("OSNet no disponible — usando grass_kmeans")
        clf_type = "grass_kmeans"
    if clf_type == "grass_kmeans":
        logger.info("Clasificador de equipos: KMeans con filtrado de cesped")
        return GrassAwareTeamClassifier()
    logger.info("Clasificador de equipos: KMeans basico")
    return ColorTeamClassifier()


def resolve_tracker_type(requested: str) -> str:
    """Tracker realmente utilizable, degradando al de respaldo si hace falta."""
    if requested == "norfair" and NORFAIR_AVAILABLE:
        return "norfair"
    if requested == "bytetrack" and BYTETRACK_AVAILABLE:
        return "bytetrack"
    if requested == "simple":
        return "simple"
    if NORFAIR_AVAILABLE:
        return "norfair"
    if BYTETRACK_AVAILABLE:
        return "bytetrack"
    return "simple"


class FootballAnalyzer:
    """Estado y métricas de un partido en curso."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = merge_config(default_runtime_config(), config)
        self.state_lock = threading.RLock()
        self.session_lock = threading.RLock()

        self.detector = Detector(self.config)
        self.model_path = self.detector.model_path

        self.kin_config = KinematicsConfig(max_history=MAX_TRACK_HISTORY)
        self.team_clf = make_team_classifier(self.config["team_classifier"], self.config["osnet_weight_path"])
        self.tracker_type = resolve_tracker_type(str(self.config["tracker_type"]))
        self._init_tracker()

        self.player_teams: Dict[str, str] = {}
        self.player_names: Dict[str, str] = {}
        self.tracks: Dict[int, Dict[str, Any]] = {}
        #: Resumen de la última fusión de tracklets, o None si no se hizo.
        self.last_merge: Optional[Dict[str, Any]] = None
        #: Frames analizados en los que se vio el balón. Es lo que permite
        #: decir si la posesión se sostiene o es un adorno.
        self.frames_with_ball = 0
        #: Campo con el que se calibró, si se usó una plantilla.
        self.pitch: Optional[PitchSpec] = None
        self.ball_positions: List[Dict[str, float]] = []
        self.ball_last_seen: Optional[int] = None
        self.possession = PossessionTracker()

        self.frame_count = 0
        self.fps_window: List[float] = []
        self.homography: Optional[np.ndarray] = None
        self._last_wall = time.monotonic()
        self._last_t: Optional[float] = None
        self._t_origin: Optional[float] = None
        #: Fuente de tiempo del análisis en curso. Se fija con la primera
        #: llamada a `process_frame` y no puede cambiar: mezclar tiempo de vídeo
        #: con reloj de pared produce métricas que parecen correctas y no lo son.
        self.time_source: Optional[str] = None
        #: Polígono que delimita dónde puede haber jugadores. Sin él, todo vale.
        self.play_area: Optional[List[Tuple[float, float]]] = None
        #: Detecciones descartadas por caer fuera. Es diagnóstico: si crece
        #: mucho, o la zona está mal puesta o el detector está viendo cosas.
        self.discarded_outside = 0
        self.elapsed_s = 0.0

        self.active_session: Optional[str] = None
        self.active_session_started_at: Optional[float] = None
        self.created_at = time.time()
        self.last_accessed_at = self.created_at
        self.metrics = self._empty_metrics()
        logger.info("FootballAnalyzer listo (tracker=%s)", self.tracker_type)

    # ── Propiedades de calibración ─────────────────────────────────────
    @property
    def pixels_per_meter(self) -> float:
        return self.kin_config.pixels_per_meter

    @pixels_per_meter.setter
    def pixels_per_meter(self, value: float) -> None:
        if value <= 0:
            raise ValueError("pixels_per_meter debe ser > 0")
        self.kin_config.pixels_per_meter = float(value)

    @property
    def is_calibrated(self) -> bool:
        return self.homography is not None

    @staticmethod
    def _empty_metrics() -> Dict[str, float]:
        return {
            "frames_processed": 0,
            "last_total_ms": 0.0,
            "last_detect_ms": 0.0,
            "last_track_ms": 0.0,
            "last_classify_ms": 0.0,
            "last_ball_ms": 0.0,
            "avg_total_ms": 0.0,
            "avg_detect_ms": 0.0,
            "avg_track_ms": 0.0,
            "avg_classify_ms": 0.0,
            "avg_ball_ms": 0.0,
        }

    # ── Trackers ───────────────────────────────────────────────────────
    def _init_tracker(self) -> None:
        self.tracker_type = resolve_tracker_type(str(self.config["tracker_type"]))
        dist = int(self.config["norfair_dist"])
        hit_max = int(self.config["norfair_hit_max"])
        if self.tracker_type == "norfair":
            self.tracker = NorfairTracker(
                distance_function="euclidean",
                distance_threshold=dist,
                hit_counter_max=hit_max,
                initialization_delay=1,
            )
            self.ball_tracker = NorfairTracker(
                distance_function="euclidean",
                distance_threshold=dist * 2,
                hit_counter_max=hit_max + 10,
                initialization_delay=0,
            )
        elif self.tracker_type == "bytetrack":
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
        else:
            self.tracker = SimpleCentroidTracker(distance_threshold=dist, max_missing=hit_max, min_hits=2)
            self.ball_tracker = SimpleCentroidTracker(distance_threshold=dist * 2, max_missing=hit_max + 10, min_hits=1)

    def _filter_play_area(self, person_xyxy, person_conf, ball_candidates):
        """Descarta lo detectado fuera de la zona de juego.

        Se filtra **antes** del tracker a propósito: un track nacido de un árbol
        o de un coche aparcado ya contamina distancias, equipos y posesión, y
        ninguna corrección posterior lo deshace.

        El punto de referencia de un jugador son sus pies —el borde inferior de
        la caja—, que es donde pisa y lo que decide si está en el campo. Para el
        balón se usa su centro.
        """
        if not self.play_area:
            return person_xyxy, person_conf, ball_candidates

        xyxy_ok, conf_ok = [], []
        for caja, conf in zip(person_xyxy, person_conf):
            pies = ((float(caja[0]) + float(caja[2])) / 2, float(caja[3]))
            if point_in_polygon(pies, self.play_area):
                xyxy_ok.append(caja)
                conf_ok.append(conf)
            else:
                self.discarded_outside += 1

        balones_ok = []
        for caja, conf in ball_candidates:
            centro = ((float(caja[0]) + float(caja[2])) / 2, (float(caja[1]) + float(caja[3])) / 2)
            if point_in_polygon(centro, self.play_area):
                balones_ok.append((caja, conf))
            else:
                self.discarded_outside += 1

        return xyxy_ok, conf_ok, balones_ok

    def set_play_area(self, points) -> None:
        """Define la zona de juego. Lanza ``PlayAreaError`` si es degenerada."""
        with self.state_lock:
            self.play_area = validate_play_area(points)

    def clear_play_area(self) -> None:
        with self.state_lock:
            self.play_area = None

    def _track_players(self, person_xyxy, person_conf) -> List[Tuple[int, float, float, float, float]]:
        if self.tracker_type == "norfair":
            return self._norfair_update(self.tracker, zip(person_xyxy, person_conf))
        if self.tracker_type == "bytetrack":
            return self._bytetrack_update(self.tracker, person_xyxy, person_conf)
        return [tuple(item) for item in self.tracker.update(person_xyxy, person_conf)]

    def _track_ball(self, ball_candidates) -> Optional[Tuple[int, int, float, float, float, float]]:
        boxes = [c[0] for c in ball_candidates]
        confs = [c[1] for c in ball_candidates]
        if self.tracker_type == "norfair":
            tracked = self._norfair_update(self.ball_tracker, zip(boxes, confs))
        elif self.tracker_type == "bytetrack":
            tracked = self._bytetrack_update(self.ball_tracker, boxes, confs)
        else:
            tracked = [tuple(item) for item in self.ball_tracker.update(boxes, confs)]
        if not tracked:
            return None
        _, x1, y1, x2, y2 = tracked[0]
        return int((x1 + x2) / 2), int((y1 + y2) / 2), float(x1), float(y1), float(x2), float(y2)

    def _norfair_update(self, tracker, pairs) -> List[Tuple[int, float, float, float, float]]:
        detections = []
        for xyxy, conf in pairs:
            cx = (float(xyxy[0]) + float(xyxy[2])) / 2
            cy = (float(xyxy[1]) + float(xyxy[3])) / 2
            detections.append(
                NorfairDetection(points=np.array([[cx, cy]]), scores=np.array([conf]), data={"xyxy": xyxy})
            )
        result = []
        for obj in tracker.update(detections=detections):
            cx, cy = obj.estimate[0]
            if obj.last_detection is not None and obj.last_detection.data:
                x1, y1, x2, y2 = obj.last_detection.data["xyxy"]
            else:
                r = float(self.config["norfair_dist"]) * 0.6
                x1, y1, x2, y2 = cx - r, cy - r, cx + r, cy + r
            result.append((int(obj.id), float(x1), float(y1), float(x2), float(y2)))
        return result

    @staticmethod
    def _bytetrack_update(tracker, boxes, confs) -> List[Tuple[int, float, float, float, float]]:
        if boxes:
            detections = sv.Detections(
                xyxy=np.asarray(boxes, dtype=float),
                confidence=np.asarray(confs, dtype=float),
                class_id=np.zeros(len(boxes), dtype=int),
            )
            tracked = tracker.update_with_detections(detections)
        else:
            tracked = tracker.update_with_detections(sv.Detections.empty())
        return [
            (int(tracked.tracker_id[i]), *(float(v) for v in tracked.xyxy[i]))
            for i in range(len(tracked))
            if tracked.tracker_id is not None
        ]

    # ── Frame principal ────────────────────────────────────────────────
    def process_frame(self, frame: np.ndarray, timestamp: Optional[float] = None) -> Dict[str, Any]:
        """Procesa un frame.

        *timestamp* son segundos de vídeo. Si falta se usa el reloj de la
        cámara, que es legítimo **sólo en directo**: en directo no existe un
        tiempo de vídeo que consultar. Lo que no es legítimo es mezclar las dos
        fuentes en el mismo análisis, y eso lanza :class:`TimeBaseError`.

        La fuente queda registrada en ``self.time_source`` y viaja hasta el
        informe. Ninguna comprobación local puede distinguir el reloj de pared
        del tiempo de vídeo —los dos son monótonos y crecen igual—, así que la
        única defensa real es declarar cuál se usó y propagarlo.
        """
        with self.state_lock:
            total_start = time.perf_counter()
            now = time.monotonic()
            wall_dt = now - self._last_wall
            self._last_wall = now
            processing_fps = self._push_fps(1.0 / max(wall_dt, 1e-6))

            fuente = TIME_SOURCE_VIDEO if timestamp is not None else TIME_SOURCE_CLOCK
            if self.time_source is None:
                self.time_source = fuente
            elif self.time_source != fuente:
                raise TimeBaseError(
                    f"este análisis empezó con base de tiempo «{self.time_source}» y "
                    f"ahora llega una muestra con base «{fuente}». Mezclarlas produce "
                    f"métricas incomparables: reinicia la sesión antes de cambiar de fuente."
                )

            t = float(timestamp) if timestamp is not None else now
            if self._t_origin is None:
                self._t_origin = t
            t -= self._t_origin
            if self._last_t is not None and t < self._last_t:
                # Timestamps que retroceden (seek del usuario): se ignora el salto.
                t = self._last_t
            dt = t - self._last_t if self._last_t is not None else 0.0
            self._last_t = t
            self.elapsed_s = t
            self.frame_count += 1

            detect_start = time.perf_counter()
            person_xyxy, person_conf, ball_candidates = self.detector.predict(frame)
            person_xyxy, person_conf, ball_candidates = self._filter_play_area(
                person_xyxy, person_conf, ball_candidates
            )
            detect_ms = (time.perf_counter() - detect_start) * 1000

            track_start = time.perf_counter()
            player_tracks = self._track_players(person_xyxy, person_conf)
            track_ms = (time.perf_counter() - track_start) * 1000

            classify_start = time.perf_counter()
            players_out = [
                self._process_player(frame, tid, (x1, y1, x2, y2), t)
                for tid, x1, y1, x2, y2 in player_tracks
            ]
            classify_ms = (time.perf_counter() - classify_start) * 1000

            ball_start = time.perf_counter()
            ball_out = self._process_ball(ball_candidates, players_out, dt)
            ball_ms = (time.perf_counter() - ball_start) * 1000

            total_ms = (time.perf_counter() - total_start) * 1000
            self._update_metrics(detect_ms, track_ms, classify_ms, ball_ms, total_ms)

            return {
                "frame": self.frame_count,
                "t": round(t, 3),
                "fps": round(processing_fps, 1),
                "players": players_out,
                "ball": ball_out,
                "stats": {
                    "total_players": len(players_out),
                    "team_1_count": sum(1 for p in players_out if p["team"] == "team_1"),
                    "team_2_count": sum(1 for p in players_out if p["team"] == "team_2"),
                    "classifier_ready": bool(getattr(self.team_clf, "is_fitted", False)),
                    "tracker": self.tracker_type,
                    "calibrated": self.is_calibrated,
                    "elapsed_s": round(t, 2),
                    "time_source": self.time_source,
                    "play_area": bool(self.play_area),
                    "discarded_outside": self.discarded_outside,
                },
                "timings_ms": {
                    "detect": round(detect_ms, 2),
                    "track": round(track_ms, 2),
                    "classify": round(classify_ms, 2),
                    "ball": round(ball_ms, 2),
                    "total": round(total_ms, 2),
                },
                "possession": self.possession.snapshot(),
            }

    def _process_player(self, frame, tid: int, bbox: Tuple[float, float, float, float], t: float) -> Dict[str, Any]:
        x1, y1, x2, y2 = bbox
        cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
        key = str(tid)

        track = self.tracks.get(tid)
        if track is None:
            track = {
                "name": self.player_names.get(key, f"#{tid}"),
                "team": "unknown",
                "kinematics": PlayerKinematics(tid, self.kin_config),
            }
            self.tracks[tid] = track

        manual_team = self.player_teams.get(key)
        if manual_team:
            track["team"] = manual_team
        else:
            predicted = self.team_clf.predict(frame, bbox, track_id=tid)
            if predicted != "unknown":
                track["team"] = predicted
        self._accumulate_appearance(track, frame, bbox)
        if key in self.player_names:
            track["name"] = self.player_names[key]

        # Se proyectan los PIES, no el centro de la caja. La homografía mapea el
        # plano del suelo, y el único punto del jugador que está sobre ese plano
        # es donde pisa: proyectar el torso —a ~0,9 m de altura— lo sitúa varios
        # metros más lejos de la cámara, y el error crece con la distancia.
        # Afectaba a todo lo que se calcula en metros: posiciones, distancias,
        # velocidades, el mini-mapa y la adjudicación de posesión.
        world = self.pixel_to_world(cx, y2)
        kin: PlayerKinematics = track["kinematics"]
        kin.update(
            Sample(
                frame=self.frame_count,
                t=t,
                x=cx,
                y=cy,
                wx=world[0] if world else None,
                wy=world[1] if world else None,
            )
        )
        track["last_seen_frame"] = self.frame_count

        return {
            "track_id": tid,
            "name": track["name"],
            "team": track["team"],
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
            "center": [cx, cy],
            "world_pos": list(world) if world else None,
            "speed_kmh": round(kin.speed_kmh, 1),
            "max_speed_kmh": round(kin.max_speed_kmh, 1),
            "total_dist_m": round(kin.total_distance_m, 1),
            "sprints": kin.sprints,
            "trail": kin.trail(20),
        }

    #: Cada cuántos frames analizados se actualiza el descriptor de apariencia.
    #: Extraerlo en todos duplicaría el trabajo del clasificador de color sin
    #: mejorar una media que ya converge en pocas muestras.
    APPEARANCE_EVERY = 5

    def _accumulate_appearance(self, track: Dict[str, Any], frame, bbox) -> None:
        """Mantiene un descriptor medio del jugador, para fusionar tracklets.

        Se guarda una media incremental y no la lista de descriptores: la lista
        crecería sin tope durante todo el partido, y la media es lo único que se
        usa después.

        **Hay dos contadores y tiene que haberlos.** ``appearance_frames`` cuenta
        frames vistos y decide cuándo tomar muestra; ``appearance_n`` cuenta
        muestras y es el peso de la media. Con uno solo —como estaba— el
        contador crecía cinco veces más rápido que las muestras, así que la
        muestra número 21 entraba con peso 1/101 en vez de 1/21: el descriptor
        se congelaba en los primeros recortes del jugador, que son justo los
        peores, y la fusión de tracklets decidía con ellos.
        """
        vistos = track.get("appearance_frames", 0)
        track["appearance_frames"] = vistos + 1
        if vistos % self.APPEARANCE_EVERY:
            return
        describe = getattr(self.team_clf, "describe", None)
        if describe is None:
            return
        try:
            descriptor = describe(frame, bbox)
        except Exception:                      # noqa: BLE001 — nunca tumbar el análisis
            return
        if descriptor is None:
            return
        descriptor = np.asarray(descriptor, dtype=np.float64).ravel()
        acumulado = track.get("appearance")
        if acumulado is None or acumulado.shape != descriptor.shape:
            track["appearance"] = descriptor
            track["appearance_n"] = 1
            return
        n = track.get("appearance_n", 1)
        track["appearance"] = (acumulado * n + descriptor) / (n + 1)
        track["appearance_n"] = n + 1

    def _build_tracklet(self, tid: int, track: Dict[str, Any]) -> Optional[Tracklet]:
        """Convierte un track del analizador en un candidato a fusión.

        Devuelve ``None`` para un track sin muestras: no hay nada que coser.
        """
        kin: PlayerKinematics = track["kinematics"]
        if not kin.samples or kin.first_t is None or kin.last_t is None:
            return None
        usar_mundo = self.is_calibrated and kin.samples[-1].has_world

        def punto(sample) -> Tuple[float, float]:
            if usar_mundo and sample.has_world:
                return float(sample.wx), float(sample.wy)
            return float(sample.x), float(sample.y)

        primero, ultimo = punto(kin.samples[0]), punto(kin.samples[-1])
        velocidad = (0.0, 0.0)
        if len(kin.samples) >= 2:
            anterior, actual = kin.samples[-2], kin.samples[-1]
            dt = actual.t - anterior.t
            if dt > 0:
                px, py = punto(anterior)
                velocidad = ((ultimo[0] - px) / dt, (ultimo[1] - py) / dt)

        # La confianza del equipo predicho se queda deliberadamente por debajo
        # del umbral de veto. La clasificación automática se midió repartiendo
        # 35/17 cuando debía ser mitad y mitad: dejarla vetar fusiones
        # propagaría su error a las identidades. Una asignación manual sí veta,
        # porque ésa la hizo una persona mirando.
        manual = str(tid) in self.player_teams
        return Tracklet(
            track_id=tid,
            first_t=kin.first_t,
            last_t=kin.last_t,
            first_xy=primero,
            last_xy=ultimo,
            last_velocity=velocidad,
            embedding=track.get("appearance"),
            team=track.get("team", "unknown"),
            team_confidence=1.0 if manual else 0.5,
            samples=len(kin.samples),
        )

    def merge_tracklets(self, config: Optional[MergeConfig] = None) -> Dict[str, Any]:
        """Cose los tracks que sean el mismo jugador partido en trozos.

        Es un post-proceso: no toca el bucle de frames y se puede llamar cuando
        el análisis ya terminó. **Modifica el estado de la sesión** —los tracks
        absorbidos desaparecen— así que no es idempotente en el sentido de que
        una segunda llamada trabaja sobre el resultado de la primera, aunque en
        la práctica converge porque ya no quedan candidatos.

        Devuelve el resumen de :func:`fcopilot.tracklets.merge_tracklets`, que
        dice cuántas identidades había y cuántas quedan. Ese número es lo que
        hay que mirar para saber si esto sirve de algo con un vídeo concreto.
        """
        if self.active_session is not None:
            # Un análisis en curso sigue alimentando esos tracks. Fusionar ahora
            # los sacaría del diccionario que el bucle de frames está usando, y
            # el propio bucle volvería a crearlos: se re-fragmentaría lo que se
            # acaba de coser. Se declina y se dice por qué.
            return {
                "identities_before": len(self.tracks),
                "identities_after": len(self.tracks),
                "merged": 0,
                "rejected_candidates": 0,
                "detail": [],
                "skipped": "analisis_en_curso",
            }
        with self.state_lock:
            if config is None:
                config = MergeConfig(
                    units="m" if self.is_calibrated else "px",
                    pixels_per_meter=self.kin_config.pixels_per_meter,
                    max_speed_kmh=self.kin_config.max_speed_kmh,
                )
            candidatos = []
            for tid, track in self.tracks.items():
                tracklet = self._build_tracklet(tid, track)
                if tracklet is not None:
                    candidatos.append(tracklet)

            resultado = merge_tracklets(candidatos, config)
            # Se absorbe de más tardío a más temprano para que la raíz acabe con
            # la velocidad instantánea del trozo que termina el último.
            for merge in sorted(resultado.merges, key=lambda m: m.gap_s):
                raiz = resultado.mapping.get(merge.tail_id, merge.tail_id)
                absorbido = self.tracks.get(merge.tail_id)
                destino = self.tracks.get(raiz)
                if absorbido is None or destino is None or raiz == merge.tail_id:
                    continue
                destino["kinematics"].absorb(absorbido["kinematics"])
                if destino.get("team", "unknown") == "unknown":
                    destino["team"] = absorbido.get("team", "unknown")
                self.tracks.pop(merge.tail_id, None)

            resumen = resultado.summary()
            resumen["units"] = config.units
            self.last_merge = resumen
            return resumen

    def _process_ball(self, ball_candidates, players_out, dt: float) -> Optional[Dict[str, Any]]:
        ball_info = self._track_ball(ball_candidates)
        if ball_info is None:
            # Sin balón visible no hay posesión que adjudicar, pero el tiempo
            # sigue corriendo: se acumula como "sin dueño".
            self.possession.update("none", dt)
            return None

        self.frames_with_ball += 1
        bcx, bcy, bx1, by1, bx2, by2 = ball_info
        self.ball_positions.append({"frame": self.frame_count, "x": bcx, "y": bcy})
        if len(self.ball_positions) > MAX_TRACK_HISTORY:
            del self.ball_positions[: len(self.ball_positions) - MAX_TRACK_HISTORY]
        self.ball_last_seen = self.frame_count

        ball_world = self.pixel_to_world(bcx, bcy)
        use_world = self.is_calibrated and ball_world is not None
        threshold = POSSESSION_DIST_M if use_world else POSSESSION_DIST_PX
        candidate, distance = PossessionTracker.nearest_holder(
            players_out, ball_world if use_world else (bcx, bcy), threshold, use_world=use_world
        )
        holder = self.possession.update(candidate, dt)

        return {
            "center": [bcx, bcy],
            "bbox": [int(bx1), int(by1), int(bx2), int(by2)],
            "world_pos": list(ball_world) if ball_world else None,
            "trail": self.ball_positions[-30:],
            "possession": holder,
            "nearest_dist": round(distance, 2) if distance != float("inf") else None,
            "possession_pct": self.possession.share(),
        }

    # ── Métricas de rendimiento ────────────────────────────────────────
    def _push_fps(self, fps: float) -> float:
        self.fps_window.append(fps)
        if len(self.fps_window) > 30:
            self.fps_window.pop(0)
        return float(np.mean(self.fps_window))

    def _update_metrics(self, detect_ms, track_ms, classify_ms, ball_ms, total_ms) -> None:
        self.metrics["frames_processed"] += 1
        n = self.metrics["frames_processed"]
        for key, value in (
            ("detect", detect_ms),
            ("track", track_ms),
            ("classify", classify_ms),
            ("ball", ball_ms),
            ("total", total_ms),
        ):
            self.metrics[f"last_{key}_ms"] = round(value, 2)
            avg = self.metrics[f"avg_{key}_ms"]
            self.metrics[f"avg_{key}_ms"] = round((avg * (n - 1) + value) / n, 2)

    # ── Overrides manuales ─────────────────────────────────────────────
    def update_name(self, track_id: str, name: str) -> None:
        with self.state_lock:
            self.player_names[str(track_id)] = name
            track = self.tracks.get(self._as_int(track_id))
            if track:
                track["name"] = name

    def update_team(self, track_id: str, team: str) -> None:
        with self.state_lock:
            self.player_teams[str(track_id)] = team
            track = self.tracks.get(self._as_int(track_id))
            if track:
                track["team"] = team

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    # ── Calibración ────────────────────────────────────────────────────
    def set_homography(self, img_points: Sequence[Sequence[float]], world_points: Sequence[Sequence[float]]) -> None:
        homography = find_homography(img_points, world_points)  # lanza CalibrationError
        with self.state_lock:
            self.homography = homography
        logger.info("Homografia calibrada con %s puntos", len(list(img_points)))

    def calibrate_from_landmarks(
        self, image_points: Dict[str, Sequence[float]], pitch_name: str = DEFAULT_PITCH
    ) -> Dict[str, Any]:
        """Calibra señalando puntos del campo **con nombre**, no coordenadas.

        Es la diferencia entre «haz clic en cuatro sitios y escribe cuánto miden
        en metros» —que nadie hace— y «haz clic en la esquina y en el punto
        central». Lanza :class:`PitchError` con un mensaje que dice qué señaló
        mal quien llama.

        Es además la puerta de entrada para calibrar de forma automática: un
        modelo de registro de campo produce este mismo diccionario, y el resto
        del sistema no distingue si lo señaló una persona o una red.
        """
        pitch = get_pitch(pitch_name)
        homography = homography_from_landmarks(image_points, pitch)   # lanza PitchError
        with self.state_lock:
            self.homography = homography
            self.pitch = pitch
        logger.info(
            "Homografia calibrada con %s puntos de referencia de %s",
            len(image_points), pitch.name,
        )
        return {"pitch": pitch.name, "source": pitch.source, "points": len(image_points)}

    def clear_homography(self) -> None:
        with self.state_lock:
            self.homography = None
            self.pitch = None

    def pixel_to_world(self, px: float, py: float) -> Optional[Tuple[float, float]]:
        return perspective_transform_point(self.homography, px, py)

    # ── Informe ────────────────────────────────────────────────────────
    def get_export(self, include_positions: bool = True) -> Dict[str, Any]:
        with self.state_lock:
            for track in self.tracks.values():
                track["kinematics"].finalize()
            return build_report(
                {tid: track for tid, track in self.tracks.items()},
                self.possession,
                frames=self.frame_count,
                duration_s=self.elapsed_s,
                calibrated=self.is_calibrated,
                config=self.public_config(),
                include_positions=include_positions,
                time_source=self.time_source or TIME_SOURCE_VIDEO,
            )

    def get_dashboard(
        self, *, merge: bool = True, config: Optional[DashboardConfig] = None
    ) -> Dict[str, Any]:
        """Panel de operación para el cuerpo técnico.

        *merge* cose antes los trozos de trayectoria, y viene activado porque
        sin eso un jugador partido en tres aparece como tres jugadores con un
        tercio de los metros cada uno — y el panel entero deja de servir. Es
        una operación que **modifica el estado de la sesión**, así que se puede
        desactivar para ver los datos crudos.
        """
        if merge:
            self.merge_tracklets()
        informe = self.get_export(include_positions=False)
        # Con `merge=False` el panel enseña los datos crudos, así que el resumen
        # de una fusión anterior no describe lo que se está enseñando: usarlo
        # daba una fragmentación inventada y, peor, callaba el aviso
        # `sin_fusion` que es justo el que corresponde.
        ultima_fusion = self.last_merge if merge else None
        with self.state_lock:
            calidad = Quality(
                calibrated=self.is_calibrated,
                time_source=self.time_source or TIME_SOURCE_VIDEO,
                players_tracked=len(self.tracks),
                identities_before_merge=(
                    ultima_fusion.get("identities_before") if ultima_fusion else None
                ),
                rejected_steps=int((informe.get("totals") or {}).get("rejected_steps", 0)),
                frames_analyzed=self.frame_count,
                frames_with_ball=self.frames_with_ball,
                pitch_name=self.pitch.name if self.pitch else None,
                pitch_source=self.pitch.source if self.pitch else None,
            )
        return build_dashboard(informe, calidad, config)

    def public_config(self) -> Dict[str, Any]:
        return {
            "model": self.model_path,
            "tracker_type": self.tracker_type,
            "detection_mode": self.config["detection_mode"],
            "team_classifier": self.config["team_classifier"],
            "confidence": self.config["confidence"],
            "imgsz": self.config["imgsz"],
            "pixels_per_meter": self.pixels_per_meter,
        }

    # ── Reinicios ──────────────────────────────────────────────────────
    def _reset_common(self) -> None:
        self._init_tracker()
        self.tracks = {}
        self.last_merge = None
        self.frames_with_ball = 0
        self.ball_positions = []
        self.ball_last_seen = None
        self.frame_count = 0
        self.fps_window = []
        self.possession = PossessionTracker()
        self.team_clf = make_team_classifier(self.config["team_classifier"], self.config["osnet_weight_path"])
        self.metrics = self._empty_metrics()
        self._last_t = None
        self._t_origin = None
        self.time_source = None
        self.discarded_outside = 0
        self.elapsed_s = 0.0

    def soft_reset(self) -> None:
        """Reinicia el tracking preservando nombres y equipos asignados a mano."""
        with self.state_lock:
            self._reset_common()

    def reset(self) -> None:
        """Reinicio completo, incluidas las asignaciones manuales."""
        with self.state_lock:
            self._reset_common()
            self.player_teams = {}
            self.player_names = {}

    def set_team_classifier(self, clf_type: str) -> None:
        with self.state_lock:
            self.config["team_classifier"] = clf_type
            self.team_clf = make_team_classifier(clf_type, self.config["osnet_weight_path"])

    def reload_model(self, path: str) -> None:
        with self.state_lock:
            self.detector.reload(path)
            self.model_path = path
            self.config["model_path"] = path

    def apply_config(self, patch: Dict[str, Any]) -> Dict[str, bool]:
        """Aplica un parche ya validado y devuelve qué se reinicializó."""
        with self.state_lock:
            reload_model = False
            reinit_tracker = False
            reinit_clf = False

            new_model = patch.get("model_path")
            if new_model and new_model != self.model_path:
                self.reload_model(new_model)
                reload_model = True

            for key in ("tracker_type", "norfair_dist", "norfair_hit_max"):
                if key in patch and patch[key] != self.config[key]:
                    self.config[key] = patch[key]
                    reinit_tracker = True

            clf = patch.get("team_classifier")
            if clf and clf != self.config["team_classifier"]:
                reinit_clf = True

            for key, value in patch.items():
                if key in ("model_path", "team_classifier"):
                    continue
                self.config[key] = value

            if reinit_tracker:
                self._init_tracker()
            if reinit_clf:
                self.set_team_classifier(clf)
            return {
                "model_reloaded": reload_model,
                "tracker_reinited": reinit_tracker,
                "classifier_reinited": reinit_clf,
            }

    # ── Sesiones ───────────────────────────────────────────────────────
    def try_acquire_session(self, session_name: str) -> bool:
        with self.session_lock:
            if self.active_session is None:
                self.active_session = session_name
                self.active_session_started_at = time.time()
                return True
            return self.active_session == session_name

    def release_session(self, session_name: str) -> None:
        with self.session_lock:
            if self.active_session == session_name:
                self.active_session = None
                self.active_session_started_at = None

    def session_status(self) -> Dict[str, Any]:
        with self.session_lock:
            return {
                "active_session": self.active_session,
                "active_for_s": round(time.time() - self.active_session_started_at, 1)
                if self.active_session_started_at
                else 0.0,
                "idle_for_s": round(time.time() - self.last_accessed_at, 1),
                "created_at": self.created_at,
                "metrics": dict(self.metrics),
            }

    def touch(self) -> None:
        with self.session_lock:
            self.last_accessed_at = time.time()

    def is_idle_expired(self, ttl_seconds: int) -> bool:
        with self.session_lock:
            if self.active_session is not None:
                return False
            return (time.time() - self.last_accessed_at) > ttl_seconds

    # ── Persistencia ───────────────────────────────────────────────────
    def serialize_state(self) -> Dict[str, Any]:
        with self.state_lock:
            return {
                "config": self.config,
                "model_path": self.model_path,
                "player_teams": self.player_teams,
                "player_names": self.player_names,
                "tracks": {
                    str(tid): {
                        "name": track["name"],
                        "team": track["team"],
                        "kinematics": track["kinematics"].to_state(),
                    }
                    for tid, track in self.tracks.items()
                },
                "ball_positions": self.ball_positions,
                "ball_last_seen": self.ball_last_seen,
                "frame_count": self.frame_count,
                "fps_window": self.fps_window,
                "pixels_per_meter": self.pixels_per_meter,
                "possession": self.possession.to_state(),
                "homography": self.homography.tolist() if self.homography is not None else None,
                # Sin esto, una sesión restaurada conserva la homografía pero
                # pierde el campo: el panel decía "calibrado" y "sin campo" a la
                # vez, y las posiciones dejaban de poder situarse en un plano.
                "pitch": self.pitch.name if self.pitch else None,
                "frames_with_ball": self.frames_with_ball,
                "elapsed_s": self.elapsed_s,
                "last_t": self._last_t,
                "time_source": self.time_source,
                "play_area": self.play_area,
                "discarded_outside": self.discarded_outside,
                "created_at": self.created_at,
                "last_accessed_at": self.last_accessed_at,
                "metrics": self.metrics,
            }

    def load_state(self, data: Dict[str, Any]) -> None:
        with self.state_lock:
            self.config = merge_config(default_runtime_config(), data.get("config"))
            self.model_path = str(data.get("model_path", self.config["model_path"]))
            self.config["model_path"] = self.model_path
            self.detector = Detector(self.config)
            self._init_tracker()
            self.team_clf = make_team_classifier(self.config["team_classifier"], self.config["osnet_weight_path"])
            self.pixels_per_meter = float(data.get("pixels_per_meter", 8.0))
            self.player_teams = {str(k): v for k, v in (data.get("player_teams") or {}).items()}
            self.player_names = {str(k): v for k, v in (data.get("player_names") or {}).items()}
            self.tracks = {
                int(tid): {
                    "name": track.get("name", f"#{tid}"),
                    "team": track.get("team", "unknown"),
                    "kinematics": PlayerKinematics.from_state(track.get("kinematics", {}), self.kin_config),
                }
                for tid, track in (data.get("tracks") or {}).items()
            }
            self.ball_positions = list(data.get("ball_positions") or [])
            self.ball_last_seen = data.get("ball_last_seen")
            self.frame_count = int(data.get("frame_count", 0))
            self.fps_window = [float(v) for v in (data.get("fps_window") or [])][-30:]
            self.possession = PossessionTracker.from_state(data.get("possession") or {})
            homography = data.get("homography")
            self.homography = np.asarray(homography, dtype=np.float64) if homography is not None else None
            nombre_campo = data.get("pitch")
            # Un campo guardado que ya no existe en la tabla no debe tumbar la
            # restauración: se pierde la etiqueta, no la sesión.
            self.pitch = PITCHES.get(nombre_campo) if nombre_campo else None
            self.frames_with_ball = int(data.get("frames_with_ball", 0) or 0)
            self.elapsed_s = float(data.get("elapsed_s", 0.0))
            self._last_t = data.get("last_t")
            self._t_origin = 0.0 if self._last_t is not None else None
            self.time_source = data.get("time_source")
            zona = data.get("play_area")
            self.play_area = [tuple(p) for p in zona] if zona else None
            self.discarded_outside = int(data.get("discarded_outside", 0))
            self.created_at = float(data.get("created_at", time.time()))
            self.last_accessed_at = float(data.get("last_accessed_at", time.time()))
            self.metrics = {**self._empty_metrics(), **(data.get("metrics") or {})}
