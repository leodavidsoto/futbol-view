"""Clasificación de equipos por color."""

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from fcopilot.teams import ColorTeamClassifier, GrassAwareTeamClassifier, get_grass_color_hue

AZUL = (200, 60, 40)
ROJO = (40, 40, 200)
CESPED = (40, 140, 40)


def campo(alto=480, ancho=854):
    frame = np.zeros((alto, ancho, 3), dtype=np.uint8)
    frame[:, :] = CESPED
    return frame


def pintar(frame, x, y, color, w=24, h=60):
    frame[y:y + h, x:x + w] = color
    return (x, y, x + w, y + h)


def escena(n_por_equipo=6):
    """Campo verde con dos equipos de camisetas bien distintas."""
    frame = campo()
    cajas_azul = [pintar(frame, 60 + i * 60, 150, AZUL) for i in range(n_por_equipo)]
    cajas_rojo = [pintar(frame, 60 + i * 60, 300, ROJO) for i in range(n_por_equipo)]
    return frame, cajas_azul, cajas_rojo


@pytest.mark.parametrize("clf_cls", [ColorTeamClassifier, GrassAwareTeamClassifier])
def test_separa_dos_kits_distintos(clf_cls):
    frame, azules, rojos = escena()
    clf = clf_cls(min_samples=8)
    for _ in range(3):
        for i, caja in enumerate(azules):
            clf.predict(frame, caja, track_id=("a", i))
        for i, caja in enumerate(rojos):
            clf.predict(frame, caja, track_id=("r", i))

    assert clf.is_fitted
    etiquetas_azules = {clf.predict(frame, c, track_id=("a", i)) for i, c in enumerate(azules)}
    etiquetas_rojas = {clf.predict(frame, c, track_id=("r", i)) for i, c in enumerate(rojos)}
    assert len(etiquetas_azules) == 1 and len(etiquetas_rojas) == 1
    assert etiquetas_azules != etiquetas_rojas
    assert etiquetas_azules | etiquetas_rojas == {"team_1", "team_2"}


def test_sin_muestras_suficientes_devuelve_unknown():
    frame, azules, _ = escena()
    clf = ColorTeamClassifier(min_samples=50)
    assert clf.predict(frame, azules[0], track_id=1) == "unknown"
    assert not clf.is_fitted


def test_un_frame_de_un_solo_color_no_entrena():
    frame = campo()
    cajas = [pintar(frame, 60 + i * 60, 150, AZUL) for i in range(8)]
    clf = ColorTeamClassifier(min_samples=8)
    for _ in range(2):
        for i, caja in enumerate(cajas):
            clf.predict(frame, caja, track_id=i)
    # Un único kit no puede partirse en dos equipos creíbles.
    assert not clf.is_fitted


def test_las_etiquetas_son_estables_entre_reajustes():
    frame, azules, rojos = escena()
    clf = ColorTeamClassifier(min_samples=8, refit_every=4)
    for _ in range(2):
        for i, caja in enumerate(azules + rojos):
            clf.predict(frame, caja, track_id=i)
    primera = [clf.predict(frame, c, track_id=i) for i, c in enumerate(azules)]
    for _ in range(6):   # fuerza varios reajustes
        for i, caja in enumerate(azules + rojos):
            clf.predict(frame, caja, track_id=i)
    segunda = [clf.predict(frame, c, track_id=i) for i, c in enumerate(azules)]
    assert primera == segunda


def test_el_voto_temporal_absorbe_una_lectura_erronea():
    frame, azules, rojos = escena()
    clf = ColorTeamClassifier(min_samples=8, vote_window=9)
    for _ in range(3):
        for i, caja in enumerate(azules + rojos):
            clf.predict(frame, caja, track_id=i)
    estable = clf.predict(frame, azules[0], track_id=0)
    # Una única observación con la camiseta del rival (un cruce) no cambia el veredicto.
    clf.predict(frame, rojos[0], track_id=0)
    assert clf.predict(frame, azules[0], track_id=0) == estable


def test_cajas_demasiado_pequenas_se_ignoran():
    frame = campo()
    clf = ColorTeamClassifier()
    assert clf._extract_features(frame, (10, 10, 12, 14)) is None
    assert clf.predict(frame, (10, 10, 12, 14), track_id=1) == "unknown"


def test_caja_fuera_del_frame():
    frame = campo()
    clf = GrassAwareTeamClassifier()
    assert clf._extract_features(frame, (-50, -50, -10, -10)) is None


def test_tono_del_cesped():
    frame = campo()
    hue = get_grass_color_hue(frame)
    assert hue is not None and 30 <= hue <= 80
    assert get_grass_color_hue(np.zeros((10, 10, 3), dtype=np.uint8)) is None


def test_el_filtro_de_cesped_cambia_las_features():
    """Con césped dentro de la caja, la variante grass-aware lo descarta."""
    frame = campo()
    pintar(frame, 110, 150, AZUL, w=12, h=30)      # camiseta estrecha…
    caja = (100, 150, 132, 210)                    # …dentro de una caja con césped
    base = ColorTeamClassifier()._extract_features(frame, caja)
    grass = GrassAwareTeamClassifier()._extract_features(frame, caja)
    assert base is not None and grass is not None
    assert not np.allclose(base, grass)
    # El tono medido por la variante grass-aware está más cerca del azul real.
    azul_hsv = cv2.cvtColor(np.uint8([[AZUL]]), cv2.COLOR_BGR2HSV)[0, 0].astype(float)
    assert abs(grass[0] - azul_hsv[0]) < abs(base[0] - azul_hsv[0])


# ── Extremos de la ventana de votos ─────────────────────────────────────
#
# El voto por track es lo que impide que un jugador cambie de equipo cada vez
# que una sombra le cambia el color de la camiseta. Estaba probado en el caso
# central y no en sus bordes: un solo voto, la ventana llena, el empate y el
# cambio a mitad. También se fija aquí el orden determinista de los centroides,
# que es lo que impide que `team_1` y `team_2` se intercambien entre reajustes.

from collections import deque

from fcopilot.teams import UNKNOWN, ColorTeamClassifier


def _con_votos(votos, ventana=15):
    """Clasificador con la cola de votos de un track ya poblada."""
    clf = ColorTeamClassifier(vote_window=ventana)
    clf._votes["t"] = deque(votos, maxlen=ventana)
    return clf


def test_un_track_sin_votos_es_desconocido():
    assert ColorTeamClassifier()._vote("t") == UNKNOWN


def test_un_track_que_no_existe_es_desconocido():
    assert _con_votos(["team_1"])._vote("otro") == UNKNOWN


def test_sin_track_id_no_hay_voto_posible():
    assert ColorTeamClassifier()._vote(None) == UNKNOWN


def test_un_solo_voto_decide():
    assert _con_votos(["team_2"])._vote("t") == "team_2"


def test_la_mayoria_gana():
    assert _con_votos(["team_1", "team_1", "team_2"])._vote("t") == "team_1"


def test_un_frame_raro_no_cambia_el_equipo():
    """El caso de uso real: una sombra tiñe la camiseta un frame."""
    assert _con_votos(["team_1"] * 9 + ["team_2"])._vote("t") == "team_1"


def test_un_empate_es_determinista():
    """Empatados, gana el que apareció primero: da igual cuál, pero no puede bailar."""
    clf = _con_votos(["team_1", "team_2"])
    assert clf._vote("t") == clf._vote("t") == "team_1"


def test_la_ventana_olvida_lo_viejo():
    """Un jugador que cambia de equipo de verdad (corrección manual) debe poder cambiar."""
    clf = _con_votos(["team_1"] * 3 + ["team_2"] * 3, ventana=4)
    assert clf._vote("t") == "team_2", "con ventana 4 sólo quedan un team_1 y tres team_2"


def test_la_ventana_esta_acotada():
    """Un partido largo no puede acumular votos sin límite."""
    clf = ColorTeamClassifier(vote_window=5)
    for _ in range(100):
        clf._votes["t"].append("team_1")
    assert len(clf._votes["t"]) == 5


def test_cada_track_vota_por_separado():
    clf = ColorTeamClassifier(vote_window=5)
    clf._votes["a"].extend(["team_1", "team_1"])
    clf._votes["b"].extend(["team_2", "team_2"])
    assert clf._vote("a") == "team_1"
    assert clf._vote("b") == "team_2"


# ── Determinismo del orden de clusters ──────────────────────────────────
def test_dos_ajustes_seguidos_no_intercambian_los_equipos():
    """Sin orden determinista, cada reajuste podía renombrar los dos equipos."""
    rng = np.random.default_rng(7)
    claro = rng.normal([20, 200, 200], 3, size=(40, 3))
    oscuro = rng.normal([120, 200, 60], 3, size=(40, 3))

    etiquetas = []
    for _ in range(3):
        clf = ColorTeamClassifier(min_samples=8)
        clf._features = [*claro, *oscuro]
        clf._fit_features()
        assert clf.is_fitted
        etiquetas.append((clf._raw_label(claro[0]), clf._raw_label(oscuro[0])))
    assert len(set(etiquetas)) == 1, f"las etiquetas bailan entre ajustes: {etiquetas}"


def test_no_ajusta_si_los_dos_grupos_son_del_mismo_color():
    """Forzar dos clusters sobre un solo kit produciría etiquetas al azar."""
    rng = np.random.default_rng(11)
    clf = ColorTeamClassifier(min_samples=8)
    clf._features = list(rng.normal([60, 120, 120], 1, size=(40, 3)))
    clf._fit_features()
    assert clf.is_fitted is False


def test_no_ajusta_con_muestras_identicas():
    clf = ColorTeamClassifier(min_samples=4)
    clf._features = [np.array([50.0, 100.0, 100.0])] * 10
    clf._fit_features()
    assert clf.is_fitted is False
