"""Comportamiento colectivo: la forma del bloque y la ocupación del campo.

Por qué esto es lo más valioso que puede dar el sistema
------------------------------------------------------
La mitad del trabajo de un entrenador es colectiva —cómo se mueve el equipo como
bloque— y es justo la parte que menos herramientas tiene fuera del fútbol
profesional. Un preparador físico al menos tiene un GPS; un entrenador de fútbol
formativo no tiene nada que le diga si su equipo juega largo o corto.

Y hay una coincidencia afortunada: **nada de lo que se calcula aquí necesita el
balón**. Amplitud, profundidad, longitud del bloque, superficie, compacidad,
altura de las líneas y ocupación de zonas salen todas de las posiciones de los
jugadores. El balón es exactamente lo que este sistema mide peor —a la distancia
de estas tomas son cuatro píxeles—, así que la parte más útil para un entrenador
resulta ser también la que podemos medir mejor.

Lo que hay que saber antes de creerse un número de aquí
-------------------------------------------------------
1. **Sin calibración esto no son metros.** Una amplitud de «340» en píxeles no
   se compara con nada, ni con otro partido ni con un valor de referencia. Quien
   llame a este módulo sin homografía obtiene números que no significan nada, y
   por eso el analizador no los calcula sin calibrar.
2. **El portero deforma la longitud del bloque.** Está treinta metros por detrás
   de todos, así que el extremo del equipo lo marca él y no la línea defensiva.
   No sabemos quién es el portero, así que se publican las dos cifras: la
   completa y una **recortada por percentiles**, que es la que se parece a lo que
   mira un entrenador.
3. **No sabemos hacia dónde ataca cada equipo.** Con una cámara y sin detectar
   porterías, llamar «defensiva» a una línea sería inventarlo. Aquí se llaman
   **más retrasada** y **más adelantada**, que es cierto sin conocer la
   dirección; quien sepa el sentido del ataque puede renombrarlas.
4. **Las líneas son un agrupamiento, no una formación.** Partir a los jugadores
   en tres grupos por su posición a lo largo del campo se parece a un 4-4-2 sólo
   cuando el equipo juega en líneas. En un desorden, devuelve tres grupos igual.
   Por eso hay un mínimo de jugadores y por eso se publica la dispersión de cada
   línea: una línea con mucha dispersión no es una línea.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from fcopilot.pitch import PitchSpec

Point = Tuple[float, float]

#: Carriles a lo ancho, de una banda a la otra. Cinco es la rejilla con la que
#: se habla en fútbol («banda», «interior», «centro»), no una elección nuestra.
CORRIDORS: Tuple[str, ...] = (
    "banda_1",
    "interior_1",
    "centro",
    "interior_2",
    "banda_2",
)

#: Tercios a lo largo. Se numeran en vez de llamarse «defensivo» y «ofensivo»
#: porque eso depende de hacia dónde ataca el equipo, y eso no lo sabemos.
THIRDS: Tuple[str, ...] = ("tercio_1", "tercio_2", "tercio_3")

#: Percentiles con los que se recorta la longitud del bloque para quitarle el
#: efecto del portero, que está siempre muy por detrás del resto.
TRIM_LOW, TRIM_HIGH = 10.0, 90.0


class CollectiveError(ValueError):
    """Los datos recibidos no permiten calcular el comportamiento colectivo."""


# ── Geometría auxiliar ──────────────────────────────────────────────────
def convex_hull(points: Sequence[Point]) -> List[Point]:
    """Envolvente convexa (cadena monótona de Andrew), en orden antihorario.

    Se implementa aquí en vez de traer scipy porque el núcleo tiene que poder
    probarse sin dependencias pesadas, que es la regla de este paquete.
    """
    unicos = sorted(set((float(x), float(y)) for x, y in points))
    if len(unicos) <= 2:
        return unicos

    def giro(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    inferior: List[Point] = []
    for p in unicos:
        while len(inferior) >= 2 and giro(inferior[-2], inferior[-1], p) <= 0:
            inferior.pop()
        inferior.append(p)
    superior: List[Point] = []
    for p in reversed(unicos):
        while len(superior) >= 2 and giro(superior[-2], superior[-1], p) <= 0:
            superior.pop()
        superior.append(p)
    return inferior[:-1] + superior[:-1]


def polygon_area(points: Sequence[Point]) -> float:
    """Área de un polígono simple, por la fórmula del cordón de zapato."""
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def percentile(valores: Sequence[float], q: float) -> float:
    """Percentil por interpolación lineal, sin numpy.

    Se evita numpy a propósito: este módulo lo consume el núcleo, que se prueba
    sin dependencias, y un percentil son cuatro líneas.
    """
    if not valores:
        raise CollectiveError("no hay valores para el percentil")
    ordenados = sorted(valores)
    if len(ordenados) == 1:
        return ordenados[0]
    posicion = (q / 100.0) * (len(ordenados) - 1)
    bajo = int(math.floor(posicion))
    alto = min(bajo + 1, len(ordenados) - 1)
    peso = posicion - bajo
    return ordenados[bajo] * (1 - peso) + ordenados[alto] * peso


# ── La forma del bloque en un instante ──────────────────────────────────
@dataclass(frozen=True)
class Shape:
    """La forma de un equipo en un instante, en metros.

    ``length_m`` es a lo largo del campo (de portería a portería) y ``width_m``
    a lo ancho, que es como lo nombra la bibliografía: *length* y *width* del
    equipo.
    """

    players: int
    centroid: Point
    length_m: float
    length_trimmed_m: float
    width_m: float
    area_m2: float
    spread_m: float

    def as_dict(self) -> Dict[str, object]:
        return {
            "players": self.players,
            "centroid": [round(self.centroid[0], 1), round(self.centroid[1], 1)],
            "length_m": round(self.length_m, 1),
            "length_trimmed_m": round(self.length_trimmed_m, 1),
            "width_m": round(self.width_m, 1),
            "area_m2": round(self.area_m2, 1),
            "spread_m": round(self.spread_m, 1),
        }


#: Jugadores mínimos para que la forma del bloque signifique algo. Con dos o
#: tres, «amplitud» es la distancia entre dos personas y no la forma de nada.
MIN_PLAYERS_FOR_SHAPE = 4


def team_shape(positions: Sequence[Point]) -> Optional[Shape]:
    """Forma del bloque, o ``None`` si hay tan pocos jugadores que no la hay.

    ``None`` es deliberado y no es un cero: con tres jugadores vistos, la
    amplitud del equipo no es pequeña, es **desconocida**, y publicarla como un
    número invitaría a compararla con la de un frame donde se vieron once.
    """
    puntos = [(float(x), float(y)) for x, y in positions]
    if len(puntos) < MIN_PLAYERS_FOR_SHAPE:
        return None

    xs = [p[0] for p in puntos]
    ys = [p[1] for p in puntos]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    dispersion = sum(math.hypot(x - cx, y - cy) for x, y in puntos) / len(puntos)

    return Shape(
        players=len(puntos),
        centroid=(cx, cy),
        length_m=max(xs) - min(xs),
        # Recortada por percentiles: el portero está treinta metros por detrás
        # de todos y marca él solo el extremo del equipo.
        length_trimmed_m=max(percentile(xs, TRIM_HIGH) - percentile(xs, TRIM_LOW), 0.0),
        width_m=max(ys) - min(ys),
        area_m2=polygon_area(convex_hull(puntos)),
        spread_m=dispersion,
    )


# ── Líneas ──────────────────────────────────────────────────────────────
#: Jugadores mínimos para intentar partir el equipo en líneas.
MIN_PLAYERS_FOR_LINES = 6


#: Tope de jugadores para el agrupamiento exacto. Por encima, la búsqueda de
#: cortes crece de forma combinatoria; un equipo no tiene tantos jugadores en
#: campo, y si llegan más es que el seguimiento está fragmentando.
MAX_PLAYERS_FOR_EXACT_LINES = 40


def split_lines(positions: Sequence[Point], lines: int = 3) -> Optional[List[List[Point]]]:
    """Agrupa a los jugadores en líneas por su posición a lo largo del campo.

    Cómo, y por qué no es un k-medias
    ---------------------------------
    Lo obvio sería un k-medias de una dimensión, y lo obvio estaba mal. Con
    inicio por cuantiles, un 3-2-1 perfectamente ordenado —tres jugadores a 20 m,
    dos a 45 y uno a 70— convergía a **3-0-3**: dejaba la línea del medio vacía y
    metía a los de 45 con el de 70. Un entrenador habría leído una formación que
    no existía, y no había nada en la salida que lo delatara.

    En una dimensión no hace falta k-medias: **las agrupaciones óptimas son
    siempre intervalos contiguos** de los valores ordenados. Así que se prueban
    todos los cortes posibles y se elige el de menor suma de cuadrados dentro de
    cada grupo. Es exacto, es determinista, y con los jugadores que caben en un
    campo cuesta nada — con once jugadores y tres líneas son 45 combinaciones.

    Devuelve las líneas ordenadas de la más retrasada a la más adelantada, o
    ``None`` si hay pocos jugadores para que agrupar signifique algo.
    """
    puntos = [(float(x), float(y)) for x, y in positions]
    if lines < 1:
        raise CollectiveError("lines debe ser >= 1")
    if len(puntos) < max(MIN_PLAYERS_FOR_LINES, lines):
        return None

    ordenados = sorted(puntos, key=lambda p: p[0])
    if len(ordenados) > MAX_PLAYERS_FOR_EXACT_LINES:
        # Recortar a los del medio antes que agrupar mal: los extremos de una
        # nube de cuarenta identidades son casi siempre falsos positivos.
        sobra = len(ordenados) - MAX_PLAYERS_FOR_EXACT_LINES
        ordenados = ordenados[sobra // 2: len(ordenados) - (sobra - sobra // 2)]

    xs = [p[0] for p in ordenados]
    mejor_corte, mejor_coste = None, math.inf
    for cortes in _combinaciones_de_corte(len(xs), lines):
        coste = 0.0
        for inicio, fin in zip((0,) + cortes, cortes + (len(xs),)):
            tramo = xs[inicio:fin]
            media = sum(tramo) / len(tramo)
            coste += sum((v - media) ** 2 for v in tramo)
            if coste >= mejor_coste:
                break
        if coste < mejor_coste:
            mejor_corte, mejor_coste = cortes, coste

    cortes = mejor_corte or ()
    return [
        ordenados[inicio:fin]
        for inicio, fin in zip((0,) + cortes, cortes + (len(xs),))
    ]


def _combinaciones_de_corte(n: int, grupos: int):
    """Todas las formas de partir *n* elementos ordenados en *grupos* no vacíos.

    Cada combinación son los índices donde empieza cada grupo a partir del
    segundo, así que ningún grupo puede quedar vacío por construcción — que es
    justo el fallo que tenía el k-medias.
    """
    from itertools import combinations

    if grupos <= 1:
        yield ()
        return
    yield from combinations(range(1, n), grupos - 1)


def line_summary(positions: Sequence[Point], lines: int = 3) -> Optional[Dict[str, object]]:
    """Altura de cada línea y separación entre ellas.

    Se llaman por su orden —de la más retrasada a la más adelantada— y no
    «defensiva» y «ofensiva»: eso depende de hacia dónde ataca el equipo, y con
    una sola cámara y sin detectar porterías no lo sabemos.

    ``spread_m`` de cada línea es la que dice si esa línea **es** una línea: con
    mucha dispersión, tres jugadores agrupados no forman nada.
    """
    grupos = split_lines(positions, lines)
    if grupos is None:
        return None

    detalle = []
    for grupo in grupos:
        xs = [p[0] for p in grupo]
        media = sum(xs) / len(xs) if xs else 0.0
        detalle.append(
            {
                "players": len(grupo),
                "x_m": round(media, 1),
                "spread_m": round(
                    sum(abs(x - media) for x in xs) / len(xs) if xs else 0.0, 1
                ),
            }
        )
    separaciones = [
        round(detalle[i + 1]["x_m"] - detalle[i]["x_m"], 1) for i in range(len(detalle) - 1)
    ]
    return {"lines": detalle, "gaps_m": separaciones}


# ── Ocupación del campo ─────────────────────────────────────────────────
@dataclass
class ZoneGrid:
    """Rejilla de tercios × carriles sobre un campo concreto.

    Tres tercios y cinco carriles es la rejilla con la que se habla en fútbol,
    no una elección de este proyecto. Es dato: cambiar el número de divisiones
    no toca ninguna función.
    """

    pitch: PitchSpec
    thirds: int = len(THIRDS)
    corridors: int = len(CORRIDORS)

    def __post_init__(self) -> None:
        if self.thirds < 1 or self.corridors < 1:
            raise CollectiveError("la rejilla necesita al menos un tercio y un carril")

    def names(self) -> List[str]:
        """Todas las zonas, en orden de lectura."""
        return [
            f"{self._third_name(i)}|{self._corridor_name(j)}"
            for i in range(self.thirds)
            for j in range(self.corridors)
        ]

    def _third_name(self, i: int) -> str:
        return THIRDS[i] if self.thirds == len(THIRDS) else f"tercio_{i + 1}"

    def _corridor_name(self, j: int) -> str:
        return CORRIDORS[j] if self.corridors == len(CORRIDORS) else f"carril_{j + 1}"

    def zone_of(self, x: float, y: float) -> str:
        """Zona en la que cae un punto. Fuera del campo se acota al borde.

        Acotar en vez de descartar es deliberado: un jugador pisando la banda
        tiene coordenadas ligeramente fuera por el error de la homografía, y
        perderlo sería perder justo al extremo que juega pegado a la cal.
        """
        i = self._index(x, self.pitch.length_m, self.thirds)
        j = self._index(y, self.pitch.width_m, self.corridors)
        return f"{self._third_name(i)}|{self._corridor_name(j)}"

    @staticmethod
    def _index(valor: float, total: float, divisiones: int) -> int:
        if total <= 0:
            return 0
        indice = int(valor / total * divisiones)
        return max(0, min(divisiones - 1, indice))


@dataclass
class Occupancy:
    """Tiempo acumulado en cada zona. Es lo que dibuja un mapa de calor."""

    grid: ZoneGrid
    seconds: Dict[str, float] = field(default_factory=dict)

    def add(self, x: float, y: float, dt_s: float) -> None:
        if dt_s <= 0:
            return
        zona = self.grid.zone_of(x, y)
        self.seconds[zona] = self.seconds.get(zona, 0.0) + dt_s

    @property
    def total_s(self) -> float:
        return sum(self.seconds.values())

    def as_dict(self) -> Dict[str, object]:
        """Segundos y porcentaje por zona, con **todas** las zonas presentes.

        Las zonas sin tiempo se emiten a cero en vez de omitirse: un hueco en la
        rejilla es información —ahí no estuvo nadie— y una rejilla incompleta se
        dibuja mal.
        """
        total = self.total_s
        return {
            "total_s": round(total, 1),
            "zones": {
                nombre: {
                    "seconds": round(self.seconds.get(nombre, 0.0), 1),
                    "pct": round(self.seconds.get(nombre, 0.0) / total * 100.0, 1)
                    if total > 0
                    else 0.0,
                }
                for nombre in self.grid.names()
            },
        }


# ── La serie temporal ───────────────────────────────────────────────────
@dataclass
class _Acumulado:
    """Sumas de una métrica, para poder dar media, mínimo y máximo sin guardar todo."""

    n: int = 0
    suma: float = 0.0
    minimo: float = math.inf
    maximo: float = -math.inf

    def add(self, valor: float) -> None:
        self.n += 1
        self.suma += valor
        self.minimo = min(self.minimo, valor)
        self.maximo = max(self.maximo, valor)

    def as_dict(self) -> Optional[Dict[str, float]]:
        if self.n == 0:
            return None
        return {
            "avg": round(self.suma / self.n, 1),
            "min": round(self.minimo, 1),
            "max": round(self.maximo, 1),
            "samples": self.n,
        }


METRICS = ("length_m", "length_trimmed_m", "width_m", "area_m2", "spread_m")


class ShapeSeries:
    """Acumula la forma del bloque de cada equipo a lo largo del partido.

    Guarda **agregados y una línea de tiempo por bloques**, no la forma de cada
    frame: un partido son decenas de miles de frames y nadie mira eso. Los
    agregados se calculan al vuelo, así que la memoria no depende de la duración.
    """

    #: Tamaño del bloque de la línea de tiempo, en segundos.
    DEFAULT_BUCKET_S = 60.0
    #: Tope de bloques, por si un vídeo trae marcas de tiempo rotas.
    MAX_BUCKETS = 400

    def __init__(self, grid: Optional[ZoneGrid] = None, bucket_s: float = DEFAULT_BUCKET_S):
        if bucket_s <= 0:
            raise CollectiveError("bucket_s debe ser > 0")
        self.grid = grid
        self.bucket_s = bucket_s
        self.metrics: Dict[str, Dict[str, _Acumulado]] = {}
        self.timeline: Dict[str, Dict[int, Dict[str, float]]] = {}
        self.occupancy: Dict[str, Occupancy] = {}
        self.lines: Dict[str, Dict[str, _Acumulado]] = {}
        self.frames = 0

    def add(
        self,
        t: float,
        dt_s: float,
        positions_by_team: Mapping[str, Sequence[Point]],
    ) -> None:
        """Registra un instante con las posiciones de cada equipo, en metros."""
        self.frames += 1
        for equipo, posiciones in positions_by_team.items():
            if self.grid is not None:
                ocupacion = self.occupancy.setdefault(equipo, Occupancy(self.grid))
                for x, y in posiciones:
                    ocupacion.add(float(x), float(y), dt_s)

            forma = team_shape(posiciones)
            if forma is None:
                continue
            acumulados = self.metrics.setdefault(equipo, {m: _Acumulado() for m in METRICS})
            for metrica in METRICS:
                acumulados[metrica].add(float(getattr(forma, metrica)))
            self._add_to_timeline(equipo, t, forma)

            resumen = line_summary(posiciones)
            if resumen and resumen["gaps_m"]:
                huecos = self.lines.setdefault(
                    equipo, {f"gap_{i}": _Acumulado() for i in range(len(resumen["gaps_m"]))}
                )
                for i, valor in enumerate(resumen["gaps_m"]):
                    if f"gap_{i}" in huecos:
                        huecos[f"gap_{i}"].add(float(valor))

    def _add_to_timeline(self, equipo: str, t: float, forma: Shape) -> None:
        indice = int(t // self.bucket_s)
        bloques = self.timeline.setdefault(equipo, {})
        bloque = bloques.get(indice)
        if bloque is None:
            if len(bloques) >= self.MAX_BUCKETS:
                return
            bloque = bloques[indice] = {m: 0.0 for m in METRICS}
            bloque["n"] = 0.0
        for metrica in METRICS:
            bloque[metrica] += float(getattr(forma, metrica))
        bloque["n"] += 1.0

    # ── Persistencia ───────────────────────────────────────────────────
    def to_state(self) -> Dict[str, object]:
        """Estado serializable.

        Se guarda porque si no, una sesión restaurada tras reiniciar el backend
        conservaría la carga física de cada jugador y perdería todo lo
        colectivo: el panel enseñaría media pestaña y nadie sabría por qué.
        """
        return {
            "bucket_s": self.bucket_s,
            "frames": self.frames,
            "metrics": {
                equipo: {m: [a.n, a.suma, a.minimo, a.maximo] for m, a in acumulados.items()}
                for equipo, acumulados in self.metrics.items()
            },
            "lines": {
                equipo: {n: [a.n, a.suma, a.minimo, a.maximo] for n, a in acumulados.items()}
                for equipo, acumulados in self.lines.items()
            },
            "timeline": {
                equipo: {str(i): dict(bloque) for i, bloque in bloques.items()}
                for equipo, bloques in self.timeline.items()
            },
            "occupancy": {
                equipo: dict(ocupacion.seconds) for equipo, ocupacion in self.occupancy.items()
            },
        }

    @classmethod
    def from_state(
        cls, state: Mapping[str, object], grid: Optional[ZoneGrid] = None
    ) -> "ShapeSeries":
        obj = cls(grid, float(state.get("bucket_s", cls.DEFAULT_BUCKET_S)))
        obj.frames = int(state.get("frames", 0))
        for destino, clave in ((obj.metrics, "metrics"), (obj.lines, "lines")):
            for equipo, acumulados in (state.get(clave) or {}).items():
                destino[equipo] = {}
                for nombre, (n, suma, minimo, maximo) in acumulados.items():
                    destino[equipo][nombre] = _Acumulado(
                        int(n), float(suma), float(minimo), float(maximo)
                    )
        for equipo, bloques in (state.get("timeline") or {}).items():
            obj.timeline[equipo] = {int(i): dict(bloque) for i, bloque in bloques.items()}
        if grid is not None:
            for equipo, segundos in (state.get("occupancy") or {}).items():
                obj.occupancy[equipo] = Occupancy(
                    grid, {str(k): float(v) for k, v in segundos.items()}
                )
        return obj

    def timeline_for(self, equipo: str) -> List[Dict[str, float]]:
        """Media de cada métrica por bloque, sin huecos en los índices."""
        bloques = self.timeline.get(equipo)
        if not bloques:
            return []
        salida: List[Dict[str, float]] = []
        for indice in range(min(bloques), max(bloques) + 1):
            bloque = bloques.get(indice)
            fila: Dict[str, float] = {"from_s": round(indice * self.bucket_s, 1)}
            n = bloque["n"] if bloque else 0.0
            for metrica in METRICS:
                fila[metrica] = round(bloque[metrica] / n, 1) if n else 0.0
            fila["samples"] = int(n)
            salida.append(fila)
        return salida

    def summary(self) -> Dict[str, object]:
        """Todo lo colectivo, por equipo."""
        equipos = sorted(set(self.metrics) | set(self.occupancy))
        return {
            "frames": self.frames,
            "bucket_s": self.bucket_s,
            "teams": {
                equipo: {
                    "shape": {
                        metrica: acumulado.as_dict()
                        for metrica, acumulado in self.metrics.get(equipo, {}).items()
                    },
                    "line_gaps_m": {
                        nombre: acumulado.as_dict()
                        for nombre, acumulado in self.lines.get(equipo, {}).items()
                    },
                    "timeline": self.timeline_for(equipo),
                    "occupancy": (
                        self.occupancy[equipo].as_dict() if equipo in self.occupancy else None
                    ),
                }
                for equipo in equipos
            },
        }
