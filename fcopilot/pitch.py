"""El campo como dato: dimensiones y puntos de referencia con nombre.

Por qué existe este módulo
--------------------------
Hasta ahora, calibrar exigía que el usuario **supiera las dimensiones de su
campo en metros** y escribiera cuatro pares de coordenadas del mundo a mano. En
la práctica eso significa que nadie calibra, y sin calibración las distancias
salen de una constante de píxeles por metro que no tiene nada que ver con el
campo que se está mirando.

Aquí el campo pasa a ser una tabla: unas dimensiones y unos puntos de referencia
**con nombre** —la esquina, el punto central, el vértice del área— derivados de
esas dimensiones. Con eso, calibrar es señalar puntos que cualquiera reconoce
sin saber cuánto miden, y la conversión a metros la hace el módulo.

Es además la pieza que permite calibrar **automáticamente**: los modelos de
registro de campo publicados (la familia de PnLCalib / «No Bells, Just
Whistles», que es lo que usan los pipelines ganadores de SoccerNet) detectan
exactamente este tipo de puntos en la imagen. Lo que hace falta para
aprovecharlos es tener el modelo del campo en metros y una función que case
nombres con nombres — que es esto.

Lo que aquí se afirma y lo que no
---------------------------------
Las medidas del campo de 11 son las del reglamento y no se discuten. **Las de
fútbol 7 y fútbol sala sí:** varían por federación, por categoría y por
instalación, y las que van aquí son las más habituales, no una verdad. Por eso
``PitchSpec`` es un dato construible: quien conozca su campo pone sus números y
obtiene los puntos de referencia coherentes con ellos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np

from fcopilot.geometry import CalibrationError, find_homography

Point = Tuple[float, float]

#: Número mínimo de correspondencias para una homografía.
MIN_CORRESPONDENCES = 4


class PitchError(ValueError):
    """El campo o los puntos de referencia pedidos no son utilizables."""


@dataclass(frozen=True)
class PitchSpec:
    """Dimensiones de un campo, en metros.

    El sistema de coordenadas del mundo tiene el **origen en la esquina** que
    queda arriba a la izquierda mirando el campo a lo largo: ``x`` crece a lo
    largo del campo (de portería a portería) y ``y`` a lo ancho. Va así, y no
    con el origen en el centro, porque es lo que hace que el minimapa sea un
    rectángulo de ``(0, 0)`` a ``(length_m, width_m)`` sin desplazamientos.
    """

    name: str
    length_m: float
    width_m: float
    penalty_depth_m: float
    penalty_width_m: float
    goal_area_depth_m: float
    goal_area_width_m: float
    penalty_spot_m: float
    centre_circle_r_m: float
    goal_width_m: float
    #: Verdad de las medidas: ``reglamento`` para las del campo de 11,
    #: ``habitual`` para las que varían por federación. Viaja al informe para
    #: que nadie tome por exacta una medida que no lo es.
    source: str = "habitual"

    def __post_init__(self) -> None:
        if self.length_m <= 0 or self.width_m <= 0:
            raise PitchError("el campo debe tener largo y ancho positivos")
        if self.penalty_width_m > self.width_m:
            raise PitchError(
                f"{self.name}: el área ({self.penalty_width_m} m) no cabe en el ancho "
                f"del campo ({self.width_m} m)"
            )
        if self.goal_area_width_m > self.penalty_width_m:
            raise PitchError(f"{self.name}: el área pequeña no cabe dentro del área grande")
        if self.goal_area_depth_m > self.penalty_depth_m:
            raise PitchError(f"{self.name}: el área pequeña es más profunda que el área grande")
        if self.penalty_depth_m * 2 >= self.length_m:
            raise PitchError(f"{self.name}: las dos áreas se solapan a lo largo del campo")
        if self.goal_width_m > self.width_m:
            raise PitchError(f"{self.name}: la portería es más ancha que el campo")
        if self.centre_circle_r_m * 2 >= min(self.length_m, self.width_m):
            raise PitchError(f"{self.name}: el círculo central no cabe en el campo")

    # ── Puntos de referencia ───────────────────────────────────────────
    def keypoints(self) -> Dict[str, Point]:
        """Puntos de referencia del campo en metros, indexados por nombre.

        Los nombres son la interfaz: quien calibre —una persona señalando en la
        imagen o un modelo de registro de campo— sólo tiene que decir *qué*
        punto es, no cuánto mide.
        """
        largo, ancho = self.length_m, self.width_m
        medio_y = ancho / 2.0
        area_y0 = medio_y - self.penalty_width_m / 2.0
        area_y1 = medio_y + self.penalty_width_m / 2.0
        peq_y0 = medio_y - self.goal_area_width_m / 2.0
        peq_y1 = medio_y + self.goal_area_width_m / 2.0
        port_y0 = medio_y - self.goal_width_m / 2.0
        port_y1 = medio_y + self.goal_width_m / 2.0

        puntos: Dict[str, Point] = {
            # Esquinas del campo
            "esquina_izq_arriba": (0.0, 0.0),
            "esquina_der_arriba": (largo, 0.0),
            "esquina_der_abajo": (largo, ancho),
            "esquina_izq_abajo": (0.0, ancho),
            # Línea de medio campo y círculo central
            "medio_arriba": (largo / 2.0, 0.0),
            "medio_abajo": (largo / 2.0, ancho),
            "centro": (largo / 2.0, medio_y),
            "circulo_arriba": (largo / 2.0, medio_y - self.centre_circle_r_m),
            "circulo_abajo": (largo / 2.0, medio_y + self.centre_circle_r_m),
            "circulo_izq": (largo / 2.0 - self.centre_circle_r_m, medio_y),
            "circulo_der": (largo / 2.0 + self.centre_circle_r_m, medio_y),
            # Punto de penalti
            "penalti_izq": (self.penalty_spot_m, medio_y),
            "penalti_der": (largo - self.penalty_spot_m, medio_y),
        }
        # Áreas y porterías de los dos lados, generadas de la misma tabla para
        # que un lado no pueda quedarse distinto del otro por un descuido.
        for lado, x_linea, signo in (("izq", 0.0, 1.0), ("der", largo, -1.0)):
            x_area = x_linea + signo * self.penalty_depth_m
            x_peq = x_linea + signo * self.goal_area_depth_m
            puntos.update(
                {
                    f"area_{lado}_linea_arriba": (x_linea, area_y0),
                    f"area_{lado}_linea_abajo": (x_linea, area_y1),
                    f"area_{lado}_frontal_arriba": (x_area, area_y0),
                    f"area_{lado}_frontal_abajo": (x_area, area_y1),
                    f"peq_{lado}_linea_arriba": (x_linea, peq_y0),
                    f"peq_{lado}_linea_abajo": (x_linea, peq_y1),
                    f"peq_{lado}_frontal_arriba": (x_peq, peq_y0),
                    f"peq_{lado}_frontal_abajo": (x_peq, peq_y1),
                    f"porteria_{lado}_arriba": (x_linea, port_y0),
                    f"porteria_{lado}_abajo": (x_linea, port_y1),
                }
            )
        return puntos

    def outline(self) -> List[Point]:
        """Perímetro del campo, en orden, para dibujarlo o usarlo como zona."""
        return [
            (0.0, 0.0),
            (self.length_m, 0.0),
            (self.length_m, self.width_m),
            (0.0, self.width_m),
        ]

    def half(self, which: str = "izq") -> List[Point]:
        """Perímetro de media cancha.

        Existe porque jugar en media cancha es el caso normal en un
        entrenamiento y en fútbol formativo, y porque la otra mitad de la imagen
        suele ser justo donde el detector inventa jugadores.
        """
        if which not in ("izq", "der"):
            raise PitchError("half(): el lado debe ser 'izq' o 'der'")
        x0, x1 = (0.0, self.length_m / 2.0) if which == "izq" else (self.length_m / 2.0, self.length_m)
        return [(x0, 0.0), (x1, 0.0), (x1, self.width_m), (x0, self.width_m)]

    def as_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "length_m": self.length_m,
            "width_m": self.width_m,
            "source": self.source,
            "keypoints": {k: [round(x, 2), round(y, 2)] for k, (x, y) in self.keypoints().items()},
            "outline": [[round(x, 2), round(y, 2)] for x, y in self.outline()],
        }


#: Campo de 11. Las medidas son las del reglamento; el largo y el ancho son los
#: más habituales dentro del rango permitido (90-120 × 45-90 m).
PITCH_11 = PitchSpec(
    name="futbol_11",
    length_m=105.0,
    width_m=68.0,
    penalty_depth_m=16.5,
    penalty_width_m=40.32,
    goal_area_depth_m=5.5,
    goal_area_width_m=18.32,
    penalty_spot_m=11.0,
    centre_circle_r_m=9.15,
    goal_width_m=7.32,
    source="reglamento",
)

#: Campo de 7. **Las medidas varían por federación**: éstas son las más
#: extendidas en fútbol formativo, no un reglamento único.
PITCH_7 = PitchSpec(
    name="futbol_7",
    length_m=60.0,
    width_m=40.0,
    penalty_depth_m=9.0,
    penalty_width_m=24.0,
    goal_area_depth_m=4.0,
    goal_area_width_m=12.0,
    penalty_spot_m=9.0,
    centre_circle_r_m=6.0,
    goal_width_m=6.0,
)

#: Fútbol sala. El área real es un arco de 6 m, no un rectángulo: aquí se
#: aproxima por su rectángulo envolvente, que sirve para calibrar —los vértices
#: se ven igual— pero **no para dibujar el área con exactitud**.
PITCH_5 = PitchSpec(
    name="futbol_sala",
    length_m=40.0,
    width_m=20.0,
    penalty_depth_m=6.0,
    penalty_width_m=15.0,
    goal_area_depth_m=3.0,
    goal_area_width_m=9.0,
    penalty_spot_m=6.0,
    centre_circle_r_m=3.0,
    goal_width_m=3.0,
)

#: Campos disponibles por nombre. Es dato: añadir uno no toca ninguna función.
PITCHES: Dict[str, PitchSpec] = {p.name: p for p in (PITCH_11, PITCH_7, PITCH_5)}
DEFAULT_PITCH = PITCH_11.name


def get_pitch(name: str) -> PitchSpec:
    """Campo por nombre, con un error que dice cuáles hay."""
    try:
        return PITCHES[name]
    except KeyError:
        disponibles = ", ".join(sorted(PITCHES))
        raise PitchError(f"campo desconocido: {name!r} (disponibles: {disponibles})") from None


def scaled_pitch(name: str, length_m: float, width_m: float) -> PitchSpec:
    """Un campo con las marcas de *name* escaladas a otras dimensiones.

    Sirve para un campo que no mide lo que dice la plantilla. **Escalar las
    marcas es una aproximación, no la realidad:** un campo más corto no tiene
    el área proporcionalmente más pequeña, la tiene reglamentaria. Es preferible
    a usar una plantilla que no corresponde, y peor que dar las medidas reales
    construyendo un ``PitchSpec`` a mano. El campo resultante queda marcado como
    ``source="escalado"`` para que eso viaje al informe.
    """
    base = get_pitch(name)
    fx = length_m / base.length_m
    fy = width_m / base.width_m
    return PitchSpec(
        name=f"{base.name}_escalado",
        length_m=length_m,
        width_m=width_m,
        penalty_depth_m=base.penalty_depth_m * fx,
        penalty_width_m=base.penalty_width_m * fy,
        goal_area_depth_m=base.goal_area_depth_m * fx,
        goal_area_width_m=base.goal_area_width_m * fy,
        penalty_spot_m=base.penalty_spot_m * fx,
        centre_circle_r_m=base.centre_circle_r_m * min(fx, fy),
        goal_width_m=base.goal_width_m * fy,
        source="escalado",
    )


def homography_from_landmarks(
    image_points: Mapping[str, Sequence[float]],
    pitch: PitchSpec,
) -> np.ndarray:
    """Homografía imagen→campo a partir de puntos de referencia **con nombre**.

    *image_points* mapea nombre de punto de referencia a su posición en píxeles.
    Los nombres son los de :meth:`PitchSpec.keypoints`, así que quien calibra no
    tiene que saber cuánto mide nada: señala la esquina y dice «esquina».

    Es también el punto de entrada para la calibración automática: un modelo de
    registro de campo produce este mismo diccionario y el resto del sistema no
    se entera de la diferencia.

    Con más de cuatro correspondencias, :func:`find_homography` resuelve por
    mínimos cuadrados, que es lo que conviene: los puntos detectados traen
    error, y cuatro exactos propagan ese error entero.
    """
    referencia = pitch.keypoints()
    desconocidos = sorted(set(image_points) - set(referencia))
    if desconocidos:
        raise PitchError(
            f"puntos de referencia desconocidos para {pitch.name}: {', '.join(desconocidos)}. "
            f"Los válidos están en PitchSpec.keypoints()."
        )
    if len(image_points) < MIN_CORRESPONDENCES:
        raise PitchError(
            f"se necesitan al menos {MIN_CORRESPONDENCES} puntos de referencia y llegaron "
            f"{len(image_points)}"
        )
    nombres = sorted(image_points)
    origen = [tuple(float(v) for v in image_points[n]) for n in nombres]
    destino = [referencia[n] for n in nombres]
    try:
        return find_homography(origen, destino)
    except CalibrationError as exc:
        # El mensaje de geometría habla de "puntos degenerados", que aquí no
        # ayuda: lo que el usuario necesita saber es qué señaló mal.
        raise PitchError(
            f"los puntos señalados no permiten calibrar ({exc}). Suele pasar cuando "
            f"están casi alineados: señala puntos repartidos por el campo, no todos "
            f"sobre la misma línea."
        ) from exc


def landmarks_for_calibration(pitch: PitchSpec, count: int = 4) -> List[str]:
    """Puntos de referencia sugeridos para calibrar a mano, en orden de utilidad.

    El orden no es arbitrario: son los que están **más repartidos por el campo**
    y los más fáciles de identificar sin dudar. Cuatro puntos casi alineados dan
    una homografía inservible, y es el error que comete todo el mundo la primera
    vez.
    """
    sugeridos = [
        "esquina_izq_arriba",
        "esquina_der_abajo",
        "esquina_der_arriba",
        "esquina_izq_abajo",
        "medio_arriba",
        "medio_abajo",
        "area_izq_frontal_arriba",
        "area_der_frontal_abajo",
        "centro",
    ]
    if count < MIN_CORRESPONDENCES:
        raise PitchError(f"calibrar necesita al menos {MIN_CORRESPONDENCES} puntos")
    return sugeridos[:count]


def project_polygon(homography: np.ndarray, polygon: Iterable[Sequence[float]]) -> List[Point]:
    """Proyecta un polígono de imagen a coordenadas de campo.

    Sirve para saber **qué trozo de campo** cubre la zona de juego dibujada por
    el usuario, que es lo que convierte «un polígono en píxeles» en «están
    jugando en media cancha».
    """
    from fcopilot.geometry import perspective_transform_point

    salida: List[Point] = []
    for punto in polygon:
        proyectado = perspective_transform_point(homography, float(punto[0]), float(punto[1]))
        if proyectado is not None:
            salida.append(proyectado)
    return salida
