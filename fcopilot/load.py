"""Carga externa: lo que un preparador físico mide de verdad.

La cinemática de ``kinematics.py`` responde «cuánto corrió y a qué velocidad».
Eso no es lo que decide una sustitución. Lo que decide una sustitución es
**cuánta de esa distancia fue a alta intensidad, cuántas aceleraciones y
frenadas hizo, y si eso está cayendo respecto de lo que el propio jugador venía
haciendo**. Este módulo calcula eso.

Por qué está separado de ``PlayerKinematics``
---------------------------------------------
La cinemática es la que decide qué tramo es válido: rechaza el salto imposible
que produce un cambio de identidad del tracker. Si la carga se calculara aparte,
recorriendo las muestras por su cuenta, las dos podrían discrepar sobre qué
tramo cuenta — y discreparían en silencio. Aquí la cinemática **alimenta** a la
carga tramo a tramo con los que ya validó, así que hay una sola definición de
tramo válido y vive en un solo sitio.

Los umbrales, y por qué son configurables
-----------------------------------------
Las bandas de velocidad de este módulo son las que usa la bibliografía de GPS
en fútbol (14,4 / 19,8 / 25,2 km/h). **No son una constante de la naturaleza:**
cada fabricante de GPS corta las bandas donde quiere, y la literatura discute
desde hace años si el umbral debe ser absoluto o relativo al máximo de cada
jugador. Por eso hay las dos cosas:

* umbrales **absolutos**, para comparar contra valores de referencia externos;
* umbrales **relativos** al pico de cada jugador (70 % y 90 %), que es lo que
  la literatura reciente recomienda para no llamar «paseo» al esfuerzo máximo
  de un central lento.

Quien compare estas cifras con las de un GPS real tiene que mirar antes con qué
bandas las cortó el GPS. Ese aviso viaja en el propio informe.

Lo que este módulo NO puede arreglar
------------------------------------
Las aceleraciones son la métrica más sensible al ruido de todo el sistema: se
calculan derivando una velocidad que ya es una derivada de una posición
estimada. Un tracker que tiembla dos píxeles produce aceleraciones inventadas.
La defensa es exigir que el esfuerzo se sostenga (``min_effort_s``), pero es una
defensa parcial: con tracking malo, el contador de aceleraciones sube. Está
declarado aquí y en el contrato a propósito.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#: Bandas de velocidad en km/h: (nombre, mínimo inclusive, máximo exclusive).
#:
#: Son dato, no condicionales: quien añada una banda obtiene su columna en el
#: informe sin tocar ninguna función. Los cortes salen de la bibliografía de GPS
#: en fútbol — 14,4 km/h (4 m/s) es donde empieza lo que se cuenta como alta
#: intensidad, 19,8 km/h (5,5 m/s) la muy alta, y 25,2 km/h (7 m/s) el sprint.
SPEED_BANDS: Tuple[Tuple[str, float, float], ...] = (
    ("caminando", 0.0, 7.2),
    ("trote", 7.2, 14.4),
    ("alta_velocidad", 14.4, 19.8),
    ("muy_alta_velocidad", 19.8, 25.2),
    ("sprint", 25.2, math.inf),
)

#: Velocidad a partir de la cual la distancia cuenta como de alta intensidad.
#: Coincide con el borde inferior de ``alta_velocidad``: la relación se comprueba
#: en las pruebas para que mover una banda no deje el umbral descolgado.
HIGH_INTENSITY_KMH = 14.4

#: Umbral de sprint absoluto, borde inferior de la banda ``sprint``.
SPRINT_KMH = 25.2

#: Aceleración y frenada por encima de las cuales el esfuerzo es de alta
#: demanda metabólica. La bibliografía usa 3 m/s² como corte habitual; algunos
#: trabajos usan 3,5. Configurable por eso.
ACCEL_THRESHOLD_MS2 = 3.0

#: Fracción del pico personal a partir de la cual el esfuerzo es de alta
#: intensidad *para ese jugador*, y a partir de la cual es su sprint.
RELATIVE_HIGH_PCT = 0.70
RELATIVE_SPRINT_PCT = 0.90


def band_for_speed(speed_kmh: float) -> str:
    """Banda de velocidad a la que pertenece *speed_kmh*."""
    for name, low, high in SPEED_BANDS:
        if low <= speed_kmh < high:
            return name
    return SPEED_BANDS[-1][0]


@dataclass
class LoadConfig:
    """Umbrales del modelo de carga. Todos en unidades de informe (km/h, m/s²)."""

    high_intensity_kmh: float = HIGH_INTENSITY_KMH
    sprint_kmh: float = SPRINT_KMH
    accel_threshold_ms2: float = ACCEL_THRESHOLD_MS2
    #: Duración mínima de un esfuerzo para que cuente. Es la única defensa
    #: contra el ruido del tracker: sin ella, cada temblor sería una
    #: aceleración.
    min_effort_s: float = 0.35
    #: Distancia mínima de un sprint para que cuente como tal. Un pico de
    #: velocidad de dos décimas no es un sprint, es ruido.
    min_sprint_m: float = 5.0
    relative_high_pct: float = RELATIVE_HIGH_PCT
    relative_sprint_pct: float = RELATIVE_SPRINT_PCT
    #: Tamaño del bloque temporal del perfil. Un minuto es lo que lee un DT.
    bucket_s: float = 60.0
    #: Ventana con la que se compara el final contra el resto para detectar
    #: caída de rendimiento.
    dropoff_window_s: float = 300.0
    #: Tiempo observado mínimo para que una tasa **por minuto** signifique algo.
    #: Sin esto, un jugador visto dos segundos que dio cuatro pasos aparece con
    #: 130 m/min de alta intensidad y encabeza el ranking de intensidad — el
    #: mismo ranking que existe precisamente para comparar esfuerzo con
    #: justicia. Extrapolar un minuto a partir de dos segundos no es medir.
    min_observed_s_for_rates: float = 30.0

    def __post_init__(self) -> None:
        if self.high_intensity_kmh <= 0:
            raise ValueError("high_intensity_kmh debe ser > 0")
        if self.sprint_kmh < self.high_intensity_kmh:
            raise ValueError("sprint_kmh no puede ser menor que high_intensity_kmh")
        if self.accel_threshold_ms2 <= 0:
            raise ValueError("accel_threshold_ms2 debe ser > 0")
        if self.min_effort_s < 0:
            raise ValueError("min_effort_s no puede ser negativo")
        if self.bucket_s <= 0:
            raise ValueError("bucket_s debe ser > 0")
        if self.dropoff_window_s <= 0:
            raise ValueError("dropoff_window_s debe ser > 0")
        if self.min_observed_s_for_rates < 0:
            raise ValueError("min_observed_s_for_rates no puede ser negativo")
        for nombre, valor in (
            ("relative_high_pct", self.relative_high_pct),
            ("relative_sprint_pct", self.relative_sprint_pct),
        ):
            if not 0.0 < valor <= 1.0:
                raise ValueError(f"{nombre} debe estar en (0, 1]")


@dataclass
class Effort:
    """Un esfuerzo continuo por encima de un umbral."""

    kind: str          # "sprint" | "aceleracion" | "frenada"
    start_s: float
    duration_s: float
    distance_m: float
    peak: float        # km/h para un sprint, m/s² para una aceleración

    def as_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "start_s": round(self.start_s, 2),
            "duration_s": round(self.duration_s, 2),
            "distance_m": round(self.distance_m, 1),
            "peak": round(self.peak, 2),
        }


@dataclass
class _Bucket:
    """Lo acumulado en un bloque de tiempo. El perfil del partido sale de aquí."""

    distance_m: float = 0.0
    high_intensity_m: float = 0.0
    sprint_m: float = 0.0
    seconds: float = 0.0


@dataclass
class _OngoingEffort:
    """Esfuerzo en curso, pendiente de saber si dura lo suficiente."""

    kind: str
    start_s: float
    duration_s: float = 0.0
    distance_m: float = 0.0
    peak: float = 0.0


class ExternalLoad:
    """Carga externa acumulada de un jugador.

    Se alimenta con ``add_step`` desde la cinemática, un tramo válido por
    llamada. No recorre muestras por su cuenta a propósito: la definición de
    tramo válido vive en un solo sitio.
    """

    #: Tope de bloques guardados. Un partido son ~120; el tope sólo evita que
    #: un vídeo con marcas de tiempo rotas haga crecer el diccionario sin fin.
    MAX_BUCKETS = 400
    #: Tope de esfuerzos guardados con detalle. Los contadores no se topan.
    MAX_EFFORTS = 200

    def __init__(self, config: Optional[LoadConfig] = None):
        self.config = config or LoadConfig()
        self.band_distance_m: Dict[str, float] = {name: 0.0 for name, _, _ in SPEED_BANDS}
        self.high_intensity_m = 0.0
        self.sprint_distance_m = 0.0
        self.accelerations = 0
        self.decelerations = 0
        self.sprint_count = 0
        self.max_accel_ms2 = 0.0
        self.max_decel_ms2 = 0.0
        self.peak_speed_kmh = 0.0
        self.efforts: List[Effort] = []
        self.buckets: Dict[int, _Bucket] = {}
        self._ongoing: Dict[str, _OngoingEffort] = {}
        self._first_t: Optional[float] = None
        self._last_t: Optional[float] = None

    # ── Alimentación ───────────────────────────────────────────────────
    def add_step(
        self,
        *,
        t_start: float,
        dt_s: float,
        distance_m: float,
        speed_start_kmh: Optional[float],
        speed_end_kmh: float,
    ) -> None:
        """Registra un tramo ya validado por la cinemática.

        *speed_end_kmh* es la velocidad **cruda** del tramo, no la suavizada: el
        suavizado exponencial aplana justamente las aceleraciones que aquí se
        quieren contar. *speed_start_kmh* es la del tramo anterior, y de la
        diferencia entre ambas sale la aceleración.

        **``speed_start_kmh=None`` significa «no se sabe», y no es lo mismo que
        cero.** En el primer tramo de un jugador no hay velocidad anterior: el
        jugador no estaba parado, es que aún no se le había visto. Tratar ese
        hueco como cero fabricaba una aceleración enorme en la primera
        observación de cada jugador —25 m/s² medidos, cuando el récord humano
        anda por 10— y contaminaba la métrica entera. Sin velocidad previa no se
        calcula aceleración; la distancia y la banda sí cuentan.
        """
        if dt_s <= 0:
            return
        t_end = t_start + dt_s
        if self._first_t is None:
            self._first_t = t_start
        self._last_t = t_end

        band = band_for_speed(speed_end_kmh)
        self.band_distance_m[band] = self.band_distance_m.get(band, 0.0) + distance_m
        self.peak_speed_kmh = max(self.peak_speed_kmh, speed_end_kmh)

        alta = speed_end_kmh >= self.config.high_intensity_kmh
        es_sprint = speed_end_kmh >= self.config.sprint_kmh
        if alta:
            self.high_intensity_m += distance_m
        if es_sprint:
            self.sprint_distance_m += distance_m

        self._add_to_bucket(t_start, dt_s, distance_m, alta, es_sprint)

        self._track_effort("sprint", es_sprint, t_start, dt_s, distance_m, speed_end_kmh)

        if speed_start_kmh is None:
            # Sin velocidad previa no hay aceleración que medir. Los esfuerzos
            # de aceleración y frenada en curso se cierran, porque este tramo no
            # puede sostenerlos.
            self._track_effort("aceleracion", False, t_start, dt_s, distance_m, 0.0)
            self._track_effort("frenada", False, t_start, dt_s, distance_m, 0.0)
            return

        # Aceleración media del tramo, en m/s². Las velocidades vienen en km/h.
        accel = (speed_end_kmh - speed_start_kmh) / 3.6 / dt_s
        self.max_accel_ms2 = max(self.max_accel_ms2, accel)
        self.max_decel_ms2 = min(self.max_decel_ms2, accel)

        umbral = self.config.accel_threshold_ms2
        self._track_effort("aceleracion", accel >= umbral, t_start, dt_s, distance_m, accel)
        self._track_effort("frenada", accel <= -umbral, t_start, dt_s, distance_m, -accel)

    def _add_to_bucket(
        self, t_start: float, dt_s: float, distance_m: float, alta: bool, es_sprint: bool
    ) -> None:
        indice = int(t_start // self.config.bucket_s)
        bucket = self.buckets.get(indice)
        if bucket is None:
            if len(self.buckets) >= self.MAX_BUCKETS:
                return
            bucket = self.buckets[indice] = _Bucket()
        bucket.distance_m += distance_m
        bucket.seconds += dt_s
        if alta:
            bucket.high_intensity_m += distance_m
        if es_sprint:
            bucket.sprint_m += distance_m

    def _track_effort(
        self,
        kind: str,
        activo: bool,
        t_start: float,
        dt_s: float,
        distance_m: float,
        magnitud: float,
    ) -> None:
        """Abre, extiende o cierra un esfuerzo del tipo *kind*."""
        curso = self._ongoing.get(kind)
        if activo:
            if curso is None:
                curso = self._ongoing[kind] = _OngoingEffort(kind=kind, start_s=t_start)
            curso.duration_s += dt_s
            curso.distance_m += distance_m
            curso.peak = max(curso.peak, magnitud)
            return
        if curso is not None:
            self._close_effort(curso)
            del self._ongoing[kind]

    def _close_effort(self, curso: _OngoingEffort) -> None:
        """Cuenta un esfuerzo si superó los mínimos; si no, lo descarta."""
        if curso.duration_s < self.config.min_effort_s:
            return
        if curso.kind == "sprint" and curso.distance_m < self.config.min_sprint_m:
            return
        if curso.kind == "sprint":
            self.sprint_count += 1
        elif curso.kind == "aceleracion":
            self.accelerations += 1
        else:
            self.decelerations += 1
        if len(self.efforts) < self.MAX_EFFORTS:
            self.efforts.append(
                Effort(
                    kind=curso.kind,
                    start_s=curso.start_s,
                    duration_s=curso.duration_s,
                    distance_m=curso.distance_m,
                    peak=curso.peak,
                )
            )

    def finalize(self) -> None:
        """Cierra los esfuerzos abiertos al terminar el análisis.

        Sin esto, un jugador que termina el partido esprintando pierde ese
        sprint — y es el que más le importa a quien lea el informe.
        """
        for curso in list(self._ongoing.values()):
            self._close_effort(curso)
        self._ongoing.clear()

    # ── Lectura ────────────────────────────────────────────────────────
    @property
    def observed_seconds(self) -> float:
        if self._first_t is None or self._last_t is None:
            return 0.0
        return max(self._last_t - self._first_t, 0.0)

    @property
    def total_distance_m(self) -> float:
        return sum(self.band_distance_m.values())

    def relative_thresholds(self) -> Dict[str, float]:
        """Umbrales personales, derivados del pico observado del jugador.

        Son ``None`` mientras no haya pico: sin una velocidad máxima observada,
        un porcentaje de ella no significa nada, y devolver 0 haría que todo
        contase como sprint.
        """
        pico = self.peak_speed_kmh
        return {
            "peak_kmh": round(pico, 1),
            "high_kmh": round(pico * self.config.relative_high_pct, 1),
            "sprint_kmh": round(pico * self.config.relative_sprint_pct, 1),
        }

    def profile(self) -> List[Dict[str, float]]:
        """Perfil por bloque de tiempo, ordenado y sin huecos intermedios.

        Los bloques sin actividad se emiten a cero en vez de omitirse: un hueco
        en la serie es información —el jugador no fue visto— y una serie con
        índices salteados se dibuja mal en cualquier gráfica.
        """
        if not self.buckets:
            return []
        bucket_s = self.config.bucket_s
        primero, ultimo = min(self.buckets), max(self.buckets)
        salida: List[Dict[str, float]] = []
        for indice in range(primero, ultimo + 1):
            bucket = self.buckets.get(indice) or _Bucket()
            salida.append(
                {
                    "from_s": round(indice * bucket_s, 1),
                    "distance_m": round(bucket.distance_m, 1),
                    "high_intensity_m": round(bucket.high_intensity_m, 1),
                    "sprint_m": round(bucket.sprint_m, 1),
                    "seconds": round(bucket.seconds, 1),
                }
            )
        return salida

    def dropoff(self) -> Optional[Dict[str, float]]:
        """Caída de intensidad del tramo final respecto del resto del partido.

        Es la métrica que responde «¿a quién cambio?». Compara los metros de
        alta intensidad **por minuto observado** de la última ventana contra los
        del tiempo anterior del mismo jugador — no contra los de otro, porque
        comparar un extremo con un central no dice nada.

        Devuelve ``None`` si no hay al menos una ventana completa de referencia:
        sin base con la que comparar, cualquier número sería una invención.
        """
        if self._first_t is None or self._last_t is None:
            return None
        bucket_s = self.config.bucket_s
        corte = self._last_t - self.config.dropoff_window_s
        if corte <= self._first_t:
            return None

        recientes: List[_Bucket] = []
        previos: List[_Bucket] = []
        for indice, bucket in self.buckets.items():
            destino = recientes if indice * bucket_s >= corte else previos
            destino.append(bucket)
        if not recientes or not previos:
            return None

        def por_minuto(bloques: List[_Bucket]) -> Optional[float]:
            segundos = sum(b.seconds for b in bloques)
            if segundos <= 0:
                return None
            return sum(b.high_intensity_m for b in bloques) / segundos * 60.0

        base = por_minuto(previos)
        reciente = por_minuto(recientes)
        if base is None or reciente is None or base <= 0:
            return None
        return {
            "baseline_hi_m_per_min": round(base, 1),
            "recent_hi_m_per_min": round(reciente, 1),
            "change_pct": round((reciente - base) / base * 100.0, 1),
            "window_s": self.config.dropoff_window_s,
        }

    def summary(self) -> Dict[str, object]:
        """Resumen de carga, con las unidades escritas en el nombre de la clave."""
        observados = self.observed_seconds
        total = self.total_distance_m
        # `None` significa «no se puede extrapolar», que no es lo mismo que 0 ni
        # que un número enorme. Quien ordene por esta clave tiene que tratarlo.
        fiable = observados >= self.config.min_observed_s_for_rates
        minutos = observados / 60.0 if fiable and observados > 0 else 0.0

        def por_minuto(valor: float) -> Optional[float]:
            return round(valor / minutos, 1) if minutos > 0 else None

        return {
            "total_dist_m": round(total, 1),
            "high_intensity_m": round(self.high_intensity_m, 1),
            "sprint_dist_m": round(self.sprint_distance_m, 1),
            "bands_m": {k: round(v, 1) for k, v in self.band_distance_m.items()},
            "sprints": self.sprint_count,
            "accelerations": self.accelerations,
            "decelerations": self.decelerations,
            "high_intensity_efforts": self.accelerations + self.decelerations + self.sprint_count,
            "max_accel_ms2": round(self.max_accel_ms2, 2) + 0.0,
            "max_decel_ms2": round(self.max_decel_ms2, 2) + 0.0,
            "peak_speed_kmh": round(self.peak_speed_kmh, 1),
            "observed_s": round(observados, 1),
            "per_minute": {
                "dist_m": por_minuto(total),
                "high_intensity_m": por_minuto(self.high_intensity_m),
                "sprint_dist_m": por_minuto(self.sprint_distance_m),
            },
            "relative_thresholds_kmh": self.relative_thresholds(),
            "dropoff": self.dropoff(),
        }

    # ── Fusión ─────────────────────────────────────────────────────────
    def absorb(self, other: "ExternalLoad") -> None:
        """Suma la carga de *other* a la propia, al coser dos tracklets.

        **No se calcula ningún tramo entre las dos.** Ésa es la trampa entera de
        fusionar tracklets: tomar la última posición de uno y la primera del
        otro como un tramo recorrido añade metros que nadie observó, y un hueco
        de 2 s con 15 m de separación son 27 km/h, por debajo del filtro de
        saltos imposibles. Se colarían sin que nada los delatara. Aquí sólo se
        suman acumuladores ya calculados, así que el hueco no aporta nada — que
        es exactamente lo correcto: no se vio.
        """
        for nombre, valor in other.band_distance_m.items():
            self.band_distance_m[nombre] = self.band_distance_m.get(nombre, 0.0) + valor
        self.high_intensity_m += other.high_intensity_m
        self.sprint_distance_m += other.sprint_distance_m
        self.accelerations += other.accelerations
        self.decelerations += other.decelerations
        self.sprint_count += other.sprint_count
        self.max_accel_ms2 = max(self.max_accel_ms2, other.max_accel_ms2)
        self.max_decel_ms2 = min(self.max_decel_ms2, other.max_decel_ms2)
        self.peak_speed_kmh = max(self.peak_speed_kmh, other.peak_speed_kmh)
        self.efforts = (self.efforts + other.efforts)[: self.MAX_EFFORTS]
        for indice, bucket in other.buckets.items():
            mio = self.buckets.get(indice)
            if mio is None:
                if len(self.buckets) >= self.MAX_BUCKETS:
                    continue
                self.buckets[indice] = _Bucket(
                    bucket.distance_m, bucket.high_intensity_m, bucket.sprint_m, bucket.seconds
                )
                continue
            mio.distance_m += bucket.distance_m
            mio.high_intensity_m += bucket.high_intensity_m
            mio.sprint_m += bucket.sprint_m
            mio.seconds += bucket.seconds
        self._first_t = _menor(self._first_t, other._first_t)
        self._last_t = _mayor(self._last_t, other._last_t)

    # ── Serialización ──────────────────────────────────────────────────
    def to_state(self) -> Dict[str, object]:
        return {
            "band_distance_m": dict(self.band_distance_m),
            "high_intensity_m": self.high_intensity_m,
            "sprint_distance_m": self.sprint_distance_m,
            "accelerations": self.accelerations,
            "decelerations": self.decelerations,
            "sprint_count": self.sprint_count,
            "max_accel_ms2": self.max_accel_ms2,
            "max_decel_ms2": self.max_decel_ms2,
            "peak_speed_kmh": self.peak_speed_kmh,
            "efforts": [e.as_dict() for e in self.efforts],
            "buckets": {
                str(i): [b.distance_m, b.high_intensity_m, b.sprint_m, b.seconds]
                for i, b in self.buckets.items()
            },
            "first_t": self._first_t,
            "last_t": self._last_t,
        }

    @classmethod
    def from_state(cls, state: Dict[str, object], config: Optional[LoadConfig] = None) -> "ExternalLoad":
        obj = cls(config)
        bandas = state.get("band_distance_m") or {}
        for name, _, _ in SPEED_BANDS:
            obj.band_distance_m[name] = float(bandas.get(name, 0.0))
        obj.high_intensity_m = float(state.get("high_intensity_m", 0.0))
        obj.sprint_distance_m = float(state.get("sprint_distance_m", 0.0))
        obj.accelerations = int(state.get("accelerations", 0))
        obj.decelerations = int(state.get("decelerations", 0))
        obj.sprint_count = int(state.get("sprint_count", 0))
        obj.max_accel_ms2 = float(state.get("max_accel_ms2", 0.0))
        obj.max_decel_ms2 = float(state.get("max_decel_ms2", 0.0))
        obj.peak_speed_kmh = float(state.get("peak_speed_kmh", 0.0))
        for raw in state.get("efforts", []) or []:
            obj.efforts.append(
                Effort(
                    kind=str(raw.get("kind", "sprint")),
                    start_s=float(raw.get("start_s", 0.0)),
                    duration_s=float(raw.get("duration_s", 0.0)),
                    distance_m=float(raw.get("distance_m", 0.0)),
                    peak=float(raw.get("peak", 0.0)),
                )
            )
        for clave, valores in (state.get("buckets") or {}).items():
            distancia, alta, sprint, segundos = (list(valores) + [0.0, 0.0, 0.0, 0.0])[:4]
            obj.buckets[int(clave)] = _Bucket(
                distance_m=float(distancia),
                high_intensity_m=float(alta),
                sprint_m=float(sprint),
                seconds=float(segundos),
            )
        obj._first_t = state.get("first_t")
        obj._last_t = state.get("last_t")
        return obj


@dataclass
class SquadLoad:
    """Agregado de plantilla, para el bloque de equipo del informe."""

    players: int = 0
    total_dist_m: float = 0.0
    high_intensity_m: float = 0.0
    sprints: int = 0
    accelerations: int = 0
    decelerations: int = 0
    bands_m: Dict[str, float] = field(default_factory=lambda: {n: 0.0 for n, _, _ in SPEED_BANDS})

    def add(self, resumen: Dict[str, object]) -> None:
        self.players += 1
        self.total_dist_m += float(resumen.get("total_dist_m", 0.0))
        self.high_intensity_m += float(resumen.get("high_intensity_m", 0.0))
        self.sprints += int(resumen.get("sprints", 0))
        self.accelerations += int(resumen.get("accelerations", 0))
        self.decelerations += int(resumen.get("decelerations", 0))
        for nombre, valor in (resumen.get("bands_m") or {}).items():
            self.bands_m[nombre] = self.bands_m.get(nombre, 0.0) + float(valor)

    def as_dict(self) -> Dict[str, object]:
        return {
            "players": self.players,
            "total_dist_m": round(self.total_dist_m, 1),
            "avg_dist_m": round(self.total_dist_m / self.players, 1) if self.players else 0.0,
            "high_intensity_m": round(self.high_intensity_m, 1),
            "avg_high_intensity_m": (
                round(self.high_intensity_m / self.players, 1) if self.players else 0.0
            ),
            "sprints": self.sprints,
            "accelerations": self.accelerations,
            "decelerations": self.decelerations,
            "bands_m": {k: round(v, 1) for k, v in self.bands_m.items()},
        }


def _menor(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Mínimo tratando ``None`` como «no consta», no como cero."""
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _mayor(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)
