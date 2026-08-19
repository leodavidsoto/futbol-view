"""Homografía y utilidades geométricas."""

import numpy as np
import pytest

from fcopilot.geometry import (
    CalibrationError,
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



def test_la_homografia_esta_normalizada():
    H = find_homography(IMG_QUAD, FIELD_QUAD)
    assert H.shape == (3, 3)
    assert H[2, 2] == pytest.approx(1.0)
    assert np.isfinite(H).all()
