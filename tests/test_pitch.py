"""Pruebas del modelo de campo.

El campo es dato, así que lo que hay que fijar es que ese dato sea coherente
consigo mismo: que las marcas quepan dentro del campo, que los dos lados sean
simétricos, y que calibrar señalando puntos con nombre dé el mismo resultado
que dar las coordenadas a mano.
"""

from __future__ import annotations

import numpy as np
import pytest

from fcopilot.geometry import perspective_transform_point
from fcopilot.pitch import (
    PITCH_5,
    PITCH_7,
    PITCH_11,
    PITCHES,
    PitchError,
    PitchSpec,
    get_pitch,
    homography_from_landmarks,
    landmarks_for_calibration,
    project_polygon,
    scaled_pitch,
)

TODOS = list(PITCHES.values())
IDS = [p.name for p in TODOS]


# ── Coherencia del dato ─────────────────────────────────────────────────
@pytest.mark.parametrize("campo", TODOS, ids=IDS)
def test_todas_las_marcas_caen_dentro_del_campo(campo: PitchSpec):
    """Una marca fuera del campo produce una homografía que parece válida.

    Y no lo es: el punto de referencia estaría en un sitio donde no hay nada que
    señalar, así que el usuario señalaría otra cosa y la calibración saldría
    torcida sin ningún error por medio.
    """
    for nombre, (x, y) in campo.keypoints().items():
        assert -0.01 <= x <= campo.length_m + 0.01, f"{nombre} se sale a lo largo"
        assert -0.01 <= y <= campo.width_m + 0.01, f"{nombre} se sale a lo ancho"


@pytest.mark.parametrize("campo", TODOS, ids=IDS)
def test_los_dos_lados_del_campo_son_simetricos(campo: PitchSpec):
    """Generar cada lado a mano dejaría uno distinto del otro y nadie lo vería."""
    puntos = campo.keypoints()
    for sufijo in ("linea_arriba", "linea_abajo", "frontal_arriba", "frontal_abajo"):
        xi, yi = puntos[f"area_izq_{sufijo}"]
        xd, yd = puntos[f"area_der_{sufijo}"]
        assert xi + xd == pytest.approx(campo.length_m)
        assert yi == pytest.approx(yd)


@pytest.mark.parametrize("campo", TODOS, ids=IDS)
def test_el_centro_esta_en_el_centro(campo: PitchSpec):
    cx, cy = campo.keypoints()["centro"]
    assert cx == pytest.approx(campo.length_m / 2)
    assert cy == pytest.approx(campo.width_m / 2)


@pytest.mark.parametrize("campo", TODOS, ids=IDS)
def test_ningun_nombre_de_punto_se_repite_entre_lados(campo: PitchSpec):
    puntos = campo.keypoints()
    assert len(puntos) == len(set(puntos))
    assert len(puntos) >= 30


def test_el_campo_de_once_lleva_las_medidas_del_reglamento():
    """Si alguien las toca, que sea a propósito."""
    assert PITCH_11.source == "reglamento"
    assert PITCH_11.penalty_depth_m == 16.5
    assert PITCH_11.penalty_spot_m == 11.0
    assert PITCH_11.centre_circle_r_m == 9.15
    assert PITCH_11.goal_width_m == 7.32


def test_los_campos_pequenos_no_se_presentan_como_reglamento():
    """Sus medidas varían por federación; decir lo contrario sería mentir."""
    assert PITCH_7.source == "habitual"
    assert PITCH_5.source == "habitual"


# ── Validación ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "cambio",
    [
        {"length_m": 0},
        {"penalty_width_m": 200.0},          # el área no cabe a lo ancho
        {"goal_area_width_m": 100.0},        # el área pequeña no cabe en la grande
        {"goal_area_depth_m": 30.0},         # más profunda que la grande
        {"penalty_depth_m": 60.0},           # las dos áreas se solapan
        {"goal_width_m": 100.0},
        {"centre_circle_r_m": 40.0},
    ],
)
def test_un_campo_imposible_se_rechaza_al_construirlo(cambio):
    base = dict(
        name="prueba", length_m=105.0, width_m=68.0, penalty_depth_m=16.5,
        penalty_width_m=40.32, goal_area_depth_m=5.5, goal_area_width_m=18.32,
        penalty_spot_m=11.0, centre_circle_r_m=9.15, goal_width_m=7.32,
    )
    base.update(cambio)
    with pytest.raises(PitchError):
        PitchSpec(**base)


def test_un_campo_desconocido_dice_cuales_hay():
    with pytest.raises(PitchError) as exc:
        get_pitch("futbol_playa")
    assert "futbol_11" in str(exc.value)


def test_el_campo_escalado_se_declara_como_escalado():
    """Escalar las marcas es una aproximación, y el informe tiene que saberlo."""
    campo = scaled_pitch("futbol_11", 90.0, 55.0)
    assert campo.source == "escalado"
    assert campo.length_m == 90.0
    assert campo.penalty_depth_m == pytest.approx(16.5 * 90 / 105)
    # Y sigue siendo un campo válido: las marcas caben.
    for _, (x, y) in campo.keypoints().items():
        assert 0 <= x <= 90.01 and 0 <= y <= 55.01


# ── Media cancha ────────────────────────────────────────────────────────
def test_media_cancha_es_la_mitad_del_campo():
    izq = PITCH_11.half("izq")
    der = PITCH_11.half("der")
    assert [p[0] for p in izq] == [0.0, 52.5, 52.5, 0.0]
    assert [p[0] for p in der] == [52.5, 105.0, 105.0, 52.5]


def test_media_cancha_exige_un_lado_valido():
    with pytest.raises(PitchError):
        PITCH_11.half("arriba")


# ── Calibración por puntos con nombre ───────────────────────────────────
def _homografia_sintetica(campo: PitchSpec) -> np.ndarray:
    """Una transformación conocida campo→imagen, para poder comprobar la vuelta."""
    return np.array(
        [
            [8.0, 1.5, 120.0],
            [0.0, 7.0, 60.0],
            [0.0, 0.004, 1.0],
        ],
        dtype=np.float64,
    )


def _proyectar(H: np.ndarray, punto):
    x, y = punto
    v = H @ np.array([x, y, 1.0])
    return (v[0] / v[2], v[1] / v[2])


def test_calibrar_señalando_nombres_recupera_las_posiciones_en_metros():
    """Es la afirmación completa del módulo: nombres dentro, metros fuera."""
    campo = PITCH_11
    mundo_a_imagen = _homografia_sintetica(campo)
    referencia = campo.keypoints()
    nombres = landmarks_for_calibration(campo, 6)
    puntos_imagen = {n: _proyectar(mundo_a_imagen, referencia[n]) for n in nombres}

    H = homography_from_landmarks(puntos_imagen, campo)

    # Un punto que NO se usó para calibrar tiene que caer donde le toca.
    esperado = referencia["penalti_der"]
    en_imagen = _proyectar(mundo_a_imagen, esperado)
    recuperado = perspective_transform_point(H, *en_imagen)
    assert recuperado is not None
    assert recuperado[0] == pytest.approx(esperado[0], abs=0.1)
    assert recuperado[1] == pytest.approx(esperado[1], abs=0.1)


def test_un_nombre_de_punto_inventado_se_rechaza_diciendolo():
    with pytest.raises(PitchError) as exc:
        homography_from_landmarks(
            {"esquina_izq_arriba": (0, 0), "banderin_de_corner": (1, 1),
             "centro": (2, 2), "medio_abajo": (3, 3)},
            PITCH_11,
        )
    assert "banderin_de_corner" in str(exc.value)


def test_con_menos_de_cuatro_puntos_no_se_calibra():
    referencia = PITCH_11.keypoints()
    with pytest.raises(PitchError) as exc:
        homography_from_landmarks(
            {n: referencia[n] for n in ("centro", "medio_arriba", "medio_abajo")},
            PITCH_11,
        )
    assert "4" in str(exc.value)


def test_puntos_casi_alineados_dan_un_error_que_dice_que_hacer():
    """Es el error que comete todo el mundo la primera vez que calibra."""
    with pytest.raises(PitchError) as exc:
        homography_from_landmarks(
            {
                "esquina_izq_arriba": (100.0, 200.0),
                "medio_arriba": (200.0, 200.0),
                "esquina_der_arriba": (300.0, 200.0),
                "circulo_arriba": (400.0, 200.0),
            },
            PITCH_11,
        )
    assert "alineados" in str(exc.value)


def test_mas_de_cuatro_puntos_absorben_el_error_de_los_detectados():
    """Con puntos que traen ruido, cuatro exactos propagan el ruido entero.

    Ésta es la razón de usar mínimos cuadrados y no una solución exacta: los
    puntos de un modelo de registro de campo **siempre** vienen con error.
    """
    campo = PITCH_11
    mundo_a_imagen = _homografia_sintetica(campo)
    referencia = campo.keypoints()
    ruido = np.random.default_rng(7).normal(0.0, 2.0, size=(9, 2))

    nombres = landmarks_for_calibration(campo, 9)
    con_ruido = {
        n: tuple(np.array(_proyectar(mundo_a_imagen, referencia[n])) + ruido[i])
        for i, n in enumerate(nombres)
    }
    H_muchos = homography_from_landmarks(con_ruido, campo)
    H_cuatro = homography_from_landmarks({n: con_ruido[n] for n in nombres[:4]}, campo)

    def error_medio(H):
        errores = []
        for nombre, mundo in referencia.items():
            en_imagen = _proyectar(mundo_a_imagen, mundo)
            recuperado = perspective_transform_point(H, *en_imagen)
            if recuperado is not None:
                errores.append(np.hypot(recuperado[0] - mundo[0], recuperado[1] - mundo[1]))
        return float(np.mean(errores))

    assert error_medio(H_muchos) < error_medio(H_cuatro)


def test_calibrar_pide_al_menos_cuatro_sugerencias():
    with pytest.raises(PitchError):
        landmarks_for_calibration(PITCH_11, 3)


def test_las_sugerencias_no_estan_todas_alineadas():
    """Sugerir cuatro puntos de la misma línea sería sugerir un error."""
    referencia = PITCH_11.keypoints()
    puntos = np.array([referencia[n] for n in landmarks_for_calibration(PITCH_11, 4)])
    assert np.ptp(puntos[:, 0]) > 1.0
    assert np.ptp(puntos[:, 1]) > 1.0


# ── Proyección de la zona de juego ──────────────────────────────────────
def test_la_zona_dibujada_se_traduce_a_metros_de_campo():
    """Es lo que convierte «un polígono en píxeles» en «juegan en media cancha»."""
    campo = PITCH_11
    mundo_a_imagen = _homografia_sintetica(campo)
    referencia = campo.keypoints()
    nombres = landmarks_for_calibration(campo, 6)
    H = homography_from_landmarks(
        {n: _proyectar(mundo_a_imagen, referencia[n]) for n in nombres}, campo
    )

    media_en_imagen = [_proyectar(mundo_a_imagen, p) for p in campo.half("izq")]
    en_metros = project_polygon(H, media_en_imagen)

    assert len(en_metros) == 4
    xs = [p[0] for p in en_metros]
    assert min(xs) == pytest.approx(0.0, abs=0.2)
    assert max(xs) == pytest.approx(campo.length_m / 2, abs=0.3)


def test_as_dict_lleva_el_origen_de_las_medidas():
    datos = PITCH_7.as_dict()
    assert datos["source"] == "habitual"
    assert "centro" in datos["keypoints"]
    assert len(datos["outline"]) == 4
