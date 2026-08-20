"""Fusión de tracklets: coser los trozos en los que se parte un jugador.

El problema, medido
-------------------
En el partido real que se analizó, el tracker produjo **51 identidades para unos
22 jugadores**. No es un fallo del tracker: en CPU hay que analizar 1 de cada 5
frames, y entre dos frames analizados un jugador se mueve lo bastante como para
que la asociación se pierda cada vez que alguien se cruza por delante. El
tracker cierra un track y abre otro.

Las consecuencias no son cosméticas. Un jugador partido en tres trozos aparece
como tres jugadores que corrieron un tercio cada uno, reparte mal los equipos
—35/17 cuando debería ser mitad y mitad— y hace que la carga por jugador no
signifique nada.

Qué hace este módulo
--------------------
Lo mismo que el post-proceso del pipeline que ganó SoccerNet Game State
Reconstruction: mirar los trozos ya cerrados y decidir cuáles son el mismo
jugador, usando tres filtros que tienen que pasarse **todos**:

1. **Tiempo.** Dos trozos del mismo jugador no pueden solaparse: nadie está en
   dos sitios a la vez. Y el hueco entre ellos no puede ser enorme.
2. **Física.** El jugador tuvo que poder recorrer la distancia en el hueco. Se
   extrapola su última velocidad y se admite un radio que crece con el hueco,
   acotado por la velocidad máxima humana.
3. **Apariencia.** Si hay descriptores —de OSNet o del clasificador de equipo—
   tienen que parecerse. Y si los dos trozos tienen equipo asignado con
   confianza y **no** coinciden, se rechaza sin mirar nada más.

Lo que este módulo NO hace, y por qué importa
----------------------------------------------
**No inventa la distancia del hueco.** Ésta es la trampa entera de fusionar
tracklets: si al coser dos trozos se toma la posición final del primero y la
inicial del segundo como un tramo recorrido, se añaden metros que nadie
observó. Un hueco de 2 s con 15 m de separación son 27 km/h — por debajo del
filtro de saltos imposibles, así que **se colarían sin que nada los delatara**.
Por eso la fusión marca la unión como discontinuidad y la cinemática no acumula
ese tramo.

Tampoco es un tracker: no ve píxeles y no corre por frame. Es un post-proceso
sobre trozos ya cerrados, y por eso se puede probar entero sin vídeo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

#: Velocidad máxima admitida para cruzar un hueco, en km/h. Por encima del
#: récord humano a propósito: el objetivo es descartar lo imposible, no lo raro.
MAX_GAP_SPEED_KMH = 40.0


class TrackletError(ValueError):
    """Los tracklets recibidos no se pueden fusionar de forma coherente."""


@dataclass
class Tracklet:
    """Un trozo de trayectoria ya cerrado, visto como candidato a fusión.

    Las posiciones van **en metros** si hay calibración y en píxeles si no. Es
    responsabilidad de quien lo construya que todos los tracklets de una misma
    fusión estén en el mismo sistema: mezclar metros y píxeles daría un radio de
    búsqueda sin sentido, y por eso ``MergeConfig`` lleva la unidad declarada.
    """

    track_id: int
    first_t: float
    last_t: float
    first_xy: Tuple[float, float]
    last_xy: Tuple[float, float]
    #: Velocidad al final del trozo, en unidades/segundo. Se usa para extrapolar.
    last_velocity: Tuple[float, float] = (0.0, 0.0)
    #: Descriptor medio de apariencia, si lo hay. Se compara por coseno.
    embedding: Optional[np.ndarray] = None
    #: Equipo asignado y su confianza (0-1). ``"unknown"`` no contradice a nadie.
    team: str = "unknown"
    team_confidence: float = 0.0
    #: Cuántas muestras tiene. Un trozo de una muestra no aporta velocidad fiable.
    samples: int = 0

    def __post_init__(self) -> None:
        if self.last_t < self.first_t:
            raise TrackletError(
                f"tracklet {self.track_id}: termina ({self.last_t:.2f}s) antes de "
                f"empezar ({self.first_t:.2f}s)"
            )
        if self.embedding is not None:
            self.embedding = np.asarray(self.embedding, dtype=np.float64).ravel()
            if self.embedding.size == 0:
                self.embedding = None

    @property
    def duration_s(self) -> float:
        return self.last_t - self.first_t

    def predict_at(self, t: float) -> Tuple[float, float]:
        """Dónde estaría el jugador en *t* si mantuviera su última velocidad.

        Extrapolar es una apuesta, y una mala si el trozo es tan corto que su
        velocidad es ruido. Con menos de dos muestras se devuelve la última
        posición conocida, que es la apuesta conservadora.
        """
        if self.samples < 2:
            return self.last_xy
        dt = t - self.last_t
        return (
            self.last_xy[0] + self.last_velocity[0] * dt,
            self.last_xy[1] + self.last_velocity[1] * dt,
        )


@dataclass
class MergeConfig:
    """Umbrales de la fusión."""

    #: Hueco máximo admitido entre dos trozos, en segundos. Más allá, la
    #: apariencia ya no basta: en 8 segundos un jugador cruza medio campo y
    #: cualquier compañero con la misma camiseta encaja igual de bien.
    max_gap_s: float = 4.0
    #: Solape máximo tolerado. Cero significa que dos trozos que coexisten
    #: aunque sea un instante no son el mismo jugador. Se admite un margen para
    #: absorber el redondeo de las marcas de tiempo.
    max_overlap_s: float = 0.05
    #: Velocidad máxima admitida para cruzar el hueco.
    max_speed_kmh: float = MAX_GAP_SPEED_KMH
    #: Radio de gracia que se suma al radio físico, para absorber el error de
    #: la detección y de la homografía.
    slack: float = 2.0
    #: Similitud de coseno mínima entre descriptores, cuando los hay.
    min_similarity: float = 0.55
    #: Confianza a partir de la cual un equipo asignado se considera firme y
    #: puede vetar una fusión.
    team_veto_confidence: float = 0.6
    #: Unidad de las posiciones: ``"m"`` o ``"px"``. Con píxeles, la velocidad
    #: máxima se traduce usando ``pixels_per_meter``.
    units: str = "m"
    pixels_per_meter: float = 8.0
    #: Duración mínima para que un trozo pueda iniciar una cadena. Los trozos de
    #: un solo frame son casi siempre falsos positivos.
    min_duration_s: float = 0.0

    def __post_init__(self) -> None:
        if self.units not in ("m", "px"):
            raise TrackletError("units debe ser 'm' o 'px'")
        if self.max_gap_s <= 0:
            raise TrackletError("max_gap_s debe ser > 0")
        if self.max_speed_kmh <= 0:
            raise TrackletError("max_speed_kmh debe ser > 0")
        if not -1.0 <= self.min_similarity <= 1.0:
            raise TrackletError("min_similarity debe estar en [-1, 1]")
        if self.pixels_per_meter <= 0:
            raise TrackletError("pixels_per_meter debe ser > 0")

    def max_speed_units_per_s(self) -> float:
        """Velocidad máxima en las unidades en las que vienen las posiciones."""
        metros_por_s = self.max_speed_kmh / 3.6
        return metros_por_s if self.units == "m" else metros_por_s * self.pixels_per_meter


@dataclass
class Merge:
    """Una unión decidida: *tail* continúa a *head*."""

    head_id: int
    tail_id: int
    gap_s: float
    distance: float
    similarity: Optional[float]
    cost: float

    def as_dict(self) -> Dict[str, object]:
        return {
            "head_id": self.head_id,
            "tail_id": self.tail_id,
            "gap_s": round(self.gap_s, 2),
            "distance": round(self.distance, 2),
            "similarity": None if self.similarity is None else round(self.similarity, 3),
            "cost": round(self.cost, 3),
        }


@dataclass
class MergeResult:
    """Resultado de una fusión.

    ``mapping`` lleva cada ``track_id`` original al identificador que lo
    representa tras coser las cadenas. Un track que no se fusionó con nadie se
    mapea a sí mismo, así que **aplicar el mapa siempre es seguro**.
    """

    mapping: Dict[int, int] = field(default_factory=dict)
    merges: List[Merge] = field(default_factory=list)
    #: Uniones que hay que tratar como discontinuidad: ``track_id`` original del
    #: trozo que arranca tras un hueco. La cinemática **no** debe acumular
    #: distancia en su primera muestra.
    discontinuities: List[int] = field(default_factory=list)
    rejected: int = 0

    @property
    def identities_before(self) -> int:
        return len(self.mapping)

    @property
    def identities_after(self) -> int:
        return len(set(self.mapping.values()))

    def summary(self) -> Dict[str, object]:
        return {
            "identities_before": self.identities_before,
            "identities_after": self.identities_after,
            "merged": len(self.merges),
            "rejected_candidates": self.rejected,
            "detail": [m.as_dict() for m in self.merges],
        }


def cosine_similarity(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> Optional[float]:
    """Similitud de coseno, o ``None`` si falta algún descriptor.

    ``None`` es distinto de 0: significa «no se puede juzgar la apariencia», y
    quien decide lo trata como «este filtro no opina», no como «no se parecen».
    """
    if a is None or b is None:
        return None
    if a.shape != b.shape:
        return None
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-12 or nb < 1e-12:
        return None
    return float(np.dot(a, b) / (na * nb))


def _teams_contradict(a: Tracklet, b: Tracklet, config: MergeConfig) -> bool:
    """¿Los equipos asignados se contradicen con firmeza?

    ``unknown`` no contradice a nadie: no saber el equipo de un trozo es lo
    normal en los primeros frames, y vetar por eso impediría precisamente las
    fusiones que más falta hacen.
    """
    if a.team == "unknown" or b.team == "unknown":
        return False
    if a.team == b.team:
        return False
    return (
        a.team_confidence >= config.team_veto_confidence
        and b.team_confidence >= config.team_veto_confidence
    )


def _candidate_cost(
    head: Tracklet, tail: Tracklet, config: MergeConfig
) -> Optional[Tuple[float, float, float, Optional[float]]]:
    """Coste de unir *tail* detrás de *head*, o ``None`` si no puede ser.

    Devuelve ``(coste, hueco_s, distancia, similitud)``. El coste combina lo
    lejos que quedó la predicción y lo poco que se parecen, normalizados a
    [0, 1] cada uno para que ninguno domine al otro por su escala.
    """
    gap = tail.first_t - head.last_t
    if gap < -config.max_overlap_s:
        return None                      # se solapan: no es el mismo jugador
    if gap > config.max_gap_s:
        return None
    gap = max(gap, 0.0)

    if _teams_contradict(head, tail, config):
        return None

    predicho = head.predict_at(tail.first_t)
    distancia = math.hypot(tail.first_xy[0] - predicho[0], tail.first_xy[1] - predicho[1])
    radio = config.max_speed_units_per_s() * gap + config.slack
    if distancia > radio:
        return None

    similitud = cosine_similarity(head.embedding, tail.embedding)
    if similitud is not None and similitud < config.min_similarity:
        return None

    # ── El coste, y el error que tenía ──────────────────────────────────
    # La primera versión normalizaba la distancia por el radio y se quedaba
    # ahí. Como el radio **crece con el hueco**, el mismo error absoluto salía
    # más barato cuanto más largo fuera el hueco: saltarse un trozo costaba
    # menos que unirse al de al lado. Con cuatro trozos consecutivos de un
    # mismo jugador, la fusión producía las cadenas 1→3 y 2→4 en vez de
    # 1→2→3→4 — dos jugadores donde había uno, cada uno con la mitad de los
    # metros, y ninguna señal de que algo hubiera ido mal.
    #
    # Por eso el hueco entra en el coste con su propio término: a igualdad de
    # ajuste espacial, gana siempre el eslabón contiguo.
    coste_espacial = min(distancia / radio, 1.0) if radio > 0 else 1.0
    coste_hueco = gap / config.max_gap_s
    base = 0.5 * coste_espacial + 0.5 * coste_hueco
    if similitud is None:
        # Sin descriptores no se puede juzgar la apariencia. Se asume neutra, lo
        # que hace que a igualdad de física gane el candidato del que sí consta
        # que se parece.
        coste = 0.7 * base + 0.3 * 0.5
    else:
        coste = 0.7 * base + 0.3 * (1.0 - similitud) / 2.0
    return coste, gap, distancia, similitud


def merge_tracklets(
    tracklets: Sequence[Tracklet], config: Optional[MergeConfig] = None
) -> MergeResult:
    """Cose los tracklets que sean el mismo jugador.

    La asignación es **codiciosa sobre el coste global**: se evalúan todos los
    pares admisibles, se ordenan por coste y se aceptan de mejor a peor mientras
    ni la cabeza ni la cola estén ya usadas. Cada trozo puede tener como mucho
    un sucesor y un predecesor, que es lo que impide que dos jugadores se cosan
    al mismo trozo.

    No es óptimo global —un Hungarian lo sería— pero es determinista, se explica
    en dos líneas y el coste de un error es una identidad de más, no una métrica
    falsa. Cuando el número de tracklets crezca hasta que importe, el sitio para
    cambiarlo es esta función y sólo ésta.
    """
    config = config or MergeConfig()
    ordenados = sorted(tracklets, key=lambda t: (t.first_t, t.track_id))
    resultado = MergeResult(mapping={t.track_id: t.track_id for t in ordenados})

    ids = [t.track_id for t in ordenados]
    if len(set(ids)) != len(ids):
        repetidos = sorted({i for i in ids if ids.count(i) > 1})
        raise TrackletError(f"hay tracklets con el mismo track_id: {repetidos}")

    candidatos: List[Tuple[float, int, int, float, float, Optional[float]]] = []
    for i, head in enumerate(ordenados):
        if head.duration_s < config.min_duration_s:
            continue
        for tail in ordenados[i + 1:]:
            if tail.first_t - head.last_t > config.max_gap_s:
                break                     # están ordenados: el resto está aún más lejos
            evaluado = _candidate_cost(head, tail, config)
            if evaluado is None:
                resultado.rejected += 1
                continue
            coste, gap, distancia, similitud = evaluado
            candidatos.append((coste, head.track_id, tail.track_id, gap, distancia, similitud))

    # El desempate por identificador mantiene el resultado estable entre
    # ejecuciones: sin él, dos candidatos con el mismo coste podrían alternarse.
    candidatos.sort(key=lambda c: (c[0], c[1], c[2]))

    con_sucesor: set = set()
    con_predecesor: set = set()
    for coste, head_id, tail_id, gap, distancia, similitud in candidatos:
        if head_id in con_sucesor or tail_id in con_predecesor:
            continue
        if _raiz(resultado.mapping, head_id) == _raiz(resultado.mapping, tail_id):
            continue                      # ya están en la misma cadena
        con_sucesor.add(head_id)
        con_predecesor.add(tail_id)
        resultado.mapping[tail_id] = _raiz(resultado.mapping, head_id)
        resultado.merges.append(
            Merge(
                head_id=head_id,
                tail_id=tail_id,
                gap_s=gap,
                distance=distancia,
                similarity=similitud,
                cost=coste,
            )
        )
        resultado.discontinuities.append(tail_id)

    # Aplanar las cadenas: todos los eslabones apuntan a la raíz, no al anterior.
    for track_id in list(resultado.mapping):
        resultado.mapping[track_id] = _raiz(resultado.mapping, track_id)
    return resultado


def _raiz(mapping: Dict[int, int], track_id: int) -> int:
    """Identificador representante de la cadena a la que pertenece *track_id*."""
    visto = set()
    actual = track_id
    while mapping.get(actual, actual) != actual:
        if actual in visto:
            # No debería pasar: la construcción evita ciclos. Si pasara, romper
            # aquí es mejor que colgarse.
            break
        visto.add(actual)
        actual = mapping[actual]
    return actual
