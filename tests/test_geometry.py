"""Homografía y utilidades geométricas."""

import numpy as np
import pytest

from fcopilot.geometry import (
    CalibrationError,
    euclidean,
    find_homography,
    perspective_transform_point,
    polygon_area,
    quad_is_degenerate,
)

IMG_QUAD = [[100.0, 80.0], [700.0, 80.0], [780.0, 420.0], [40.0, 420.0]]
FIELD_QUAD = [[0.0, 0.0], [105.0, 0.0], [105.0, 68.0], [0.0, 68.0]]


def test_las_esquinas_mapean_al_campo():
    H = find_homography(IMG_QUAD, FIELD_QUAD)
    for img, world in zip(IMG_QUAD, FIELD_QUAD):
        got = perspective_transform_point(H, *img)
        assert got == pytest.approx(tuple(world), abs=1e-6)


def test_homografia_de_identidad():
    quad = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    H = find_homography(quad, quad)
    assert perspective_transform_point(H, 3.0, 7.0) == pytest.approx((3.0, 7.0), abs=1e-9)


def test_escalado_uniforme():
    src = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
    dst = [[0.0, 0.0], [50.0, 0.0], [50.0, 50.0], [0.0, 50.0]]
    H = find_homography(src, dst)
    assert perspective_transform_point(H, 40.0, 80.0) == pytest.approx((20.0, 40.0), abs=1e-9)


def test_sin_homografia_devuelve_none():
    assert perspective_transform_point(None, 1.0, 2.0) is None


def test_acepta_mas_de_cuatro_puntos():
    src = IMG_QUAD + [[400.0, 250.0]]
    dst = FIELD_QUAD + [list(perspective_transform_point(find_homography(IMG_QUAD, FIELD_QUAD), 400.0, 250.0))]
    H = find_homography(src, dst)
    assert perspective_transform_point(H, 400.0, 250.0) == pytest.approx(tuple(dst[-1]), abs=1e-4)


@pytest.mark.parametrize(
    "puntos",
    [
        [[0, 0], [1, 1], [2, 2], [3, 3]],          # colineales
        [[0, 0], [0, 0], [10, 0], [10, 10]],       # repetidos
    ],
)
def test_puntos_degenerados_se_rechazan(puntos):
    assert quad_is_degenerate(puntos)
    with pytest.raises(CalibrationError):
        find_homography(puntos, FIELD_QUAD)


def test_faltan_puntos():
    with pytest.raises(CalibrationError):
        find_homography([[0, 0], [1, 0], [1, 1]], FIELD_QUAD[:3])


def test_tamanos_distintos():
    with pytest.raises(CalibrationError):
        find_homography(IMG_QUAD, FIELD_QUAD + [[1.0, 1.0]])


def test_valores_no_finitos():
    with pytest.raises(CalibrationError):
        find_homography([[0, 0], [float("nan"), 0], [1, 1], [0, 1]], FIELD_QUAD)


def test_puntos_mal_formados():
    with pytest.raises(CalibrationError):
        find_homography([[0, 0, 0]] * 4, FIELD_QUAD)


def test_area_de_poligono():
    assert polygon_area([[0, 0], [4, 0], [4, 3], [0, 3]]) == pytest.approx(12.0)
    assert polygon_area([[0, 0], [1, 1]]) == 0.0


def test_distancia_euclidea():
    assert euclidean((0, 0), (3, 4)) == pytest.approx(5.0)


def test_la_homografia_esta_normalizada():
    H = find_homography(IMG_QUAD, FIELD_QUAD)
    assert H.shape == (3, 3)
    assert H[2, 2] == pytest.approx(1.0)
    assert np.isfinite(H).all()


# ── Zona de juego ───────────────────────────────────────────────────────
from fcopilot.geometry import PlayAreaError, point_in_polygon, validate_play_area

CUADRO = [(0, 0), (100, 0), (100, 100), (0, 100)]
#: Un campo visto en perspectiva no es un rectángulo: es un trapecio.
TRAPECIO = [(400, 200), (1500, 200), (1700, 600), (200, 600)]


def test_un_punto_dentro_esta_dentro():
    assert point_in_polygon((50, 50), CUADRO) is True


def test_un_punto_fuera_esta_fuera():
    assert point_in_polygon((150, 50), CUADRO) is False
    assert point_in_polygon((50, -10), CUADRO) is False


def test_el_borde_cuenta_como_dentro():
    """Un jugador sobre la línea de banda está en juego; dejarlo fuera por un
    píxel sería peor que el falso positivo que esto evita."""
    assert point_in_polygon((0, 50), CUADRO) is True
    assert point_in_polygon((100, 100), CUADRO) is True


def test_sin_zona_definida_todo_vale():
    assert point_in_polygon((9999, 9999), None) is True
    assert point_in_polygon((9999, 9999), []) is True


def test_funciona_con_un_trapecio_de_perspectiva():
    assert point_in_polygon((950, 400), TRAPECIO) is True     # centro del campo
    assert point_in_polygon((950, 100), TRAPECIO) is False    # horizonte, arriba
    assert point_in_polygon((950, 900), TRAPECIO) is False    # delante del campo
    assert point_in_polygon((100, 400), TRAPECIO) is False    # fuera por la izquierda


def test_un_poligono_concavo_se_resuelve_bien():
    ele = [(0, 0), (100, 0), (100, 40), (40, 40), (40, 100), (0, 100)]
    assert point_in_polygon((20, 20), ele) is True
    assert point_in_polygon((80, 80), ele) is False, "la muesca de la L está fuera"


def test_valida_y_normaliza_los_vertices():
    assert validate_play_area(CUADRO) == [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


def test_menos_de_tres_vertices_no_delimita_nada():
    with pytest.raises(PlayAreaError, match="al menos"):
        validate_play_area([(0, 0), (10, 10)])


def test_una_zona_degenerada_se_rechaza():
    """Tres puntos alineados no encierran área: filtrarían absolutamente todo."""
    with pytest.raises(PlayAreaError, match="degenerada"):
        validate_play_area([(0, 0), (50, 50), (100, 100), (10, 10)])


def test_el_mensaje_de_zona_degenerada_dice_qué_mirar():
    with pytest.raises(PlayAreaError) as exc:
        validate_play_area([(0, 0), (1, 1), (2, 2)])
    assert "alineados" in str(exc.value)


# ── Cuadriláteros: el orden de los clics no puede invalidar la calibración ──
def test_las_cuatro_esquinas_en_zigzag_no_son_degeneradas():
    """Cuatro esquinas válidas señaladas en orden Z se rechazaban.

    `quad_is_degenerate` medía el área del polígono, que depende del orden: el
    polígono cruzado que forman arriba-izquierda, arriba-derecha,
    abajo-izquierda, abajo-derecha tiene área **exactamente cero** por la
    fórmula del cordón. El usuario recibía «los puntos son colineales» sobre
    cuatro puntos que no lo eran, y la única salida era volver a hacer clic en
    otro orden sin saber por qué.
    """
    zigzag = [(105.0, 68.0), (105.0, 0.0), (0.0, 68.0), (0.0, 0.0)]
    assert not quad_is_degenerate(zigzag)
    assert polygon_area(zigzag) == 0.0      # el motivo del fallo, aún presente


def test_la_calibracion_da_el_mismo_resultado_en_cualquier_orden_de_clic():
    """Una homografía no depende de en qué orden se señalaron sus puntos."""
    imagen = [(100.0, 100.0), (500.0, 120.0), (520.0, 400.0), (80.0, 380.0)]
    mundo = [(0.0, 0.0), (105.0, 0.0), (105.0, 68.0), (0.0, 68.0)]
    orden = [0, 2, 1, 3]

    directa = find_homography(imagen, mundo)
    barajada = find_homography([imagen[i] for i in orden], [mundo[i] for i in orden])

    for px, py in imagen:
        a = perspective_transform_point(directa, px, py)
        b = perspective_transform_point(barajada, px, py)
        assert a is not None and b is not None
        assert a[0] == pytest.approx(b[0], abs=1e-6)
        assert a[1] == pytest.approx(b[1], abs=1e-6)


@pytest.mark.parametrize(
    "puntos",
    [
        [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0)],        # los 4 alineados
        [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (5.0, 40.0)],        # 3 alineados
        [(0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (0.0, 10.0)],        # repetido
        [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)],           # minúsculo
    ],
)
def test_lo_que_si_es_degenerado_se_sigue_rechazando(puntos):
    assert quad_is_degenerate(puntos)


def test_con_mas_de_cuatro_puntos_un_trio_alineado_no_invalida_el_conjunto():
    """Se comprobaban sólo los cuatro PRIMEROS, y eso era arbitrario e incorrecto.

    El punto central del campo está sobre la diagonal que une dos esquinas
    opuestas. Señalar «esquina, esquina, centro» entre seis puntos perfectamente
    resolubles por mínimos cuadrados tumbaba la calibración con un mensaje que
    hablaba de puntos colineales y no decía cuáles ni qué hacer.
    """
    mundo = [
        (0.0, 0.0), (105.0, 68.0), (105.0, 0.0),      # incluye el trío con el centro
        (52.5, 34.0),                                  # centro: sobre las dos diagonales
        (0.0, 68.0), (52.5, 0.0),
    ]
    H = np.array([[8.0, 1.5, 120.0], [0.0, 7.0, 60.0], [0.0, 0.004, 1.0]])

    def proyectar(p):
        v = H @ np.array([p[0], p[1], 1.0])
        return (v[0] / v[2], v[1] / v[2])

    imagen = [proyectar(p) for p in mundo]
    recuperada = find_homography(imagen, mundo)

    for px_py, esperado in zip(imagen, mundo):
        salida = perspective_transform_point(recuperada, *px_py)
        assert salida is not None
        assert salida[0] == pytest.approx(esperado[0], abs=0.05)
        assert salida[1] == pytest.approx(esperado[1], abs=0.05)


def test_muchos_puntos_todos_sobre_una_recta_siguen_siendo_degenerados():
    """Lo que impide resolver no es un trío alineado: es que no quede ninguno suelto."""
    imagen = [(float(i) * 10.0, 100.0) for i in range(8)]
    mundo = [(float(i) * 5.0, 0.0) for i in range(8)]
    with pytest.raises(CalibrationError):
        find_homography(imagen, mundo)
