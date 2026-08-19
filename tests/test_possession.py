"""Posesión: histéresis, porcentajes coherentes y contabilidad en segundos."""

import pytest

from fcopilot.possession import PossessionTracker

JUGADORES = [
    {"team": "team_1", "center": [100, 100], "world_pos": [10.0, 10.0]},
    {"team": "team_2", "center": [400, 100], "world_pos": [40.0, 10.0]},
]


def alimentar(tracker: PossessionTracker, equipo: str, veces: int, dt: float = 0.1) -> None:
    for _ in range(veces):
        tracker.update(equipo, dt)


def test_hace_falta_histeresis_para_cambiar_de_dueno():
    tracker = PossessionTracker(confirm_frames=3)
    assert tracker.update("team_1", 0.1) == "none"
    assert tracker.update("team_1", 0.1) == "none"
    assert tracker.update("team_1", 0.1) == "team_1"


def test_un_frame_suelto_del_rival_no_roba_la_posesion():
    tracker = PossessionTracker(confirm_frames=3)
    alimentar(tracker, "team_1", 5)
    assert tracker.update("team_2", 0.1) == "team_1"
    assert tracker.update("team_1", 0.1) == "team_1"
    assert tracker.changes == 1


def test_el_reparto_entre_equipos_suma_cien():
    tracker = PossessionTracker(confirm_frames=1)
    alimentar(tracker, "team_1", 30)
    alimentar(tracker, "team_2", 10)
    share = tracker.share()
    assert share["team_1"] + share["team_2"] == pytest.approx(100.0)
    assert share["team_1"] == pytest.approx(75.0, abs=0.1)


def test_los_porcentajes_totales_suman_cien_con_balon_suelto():
    tracker = PossessionTracker(confirm_frames=1)
    alimentar(tracker, "team_1", 10)
    alimentar(tracker, "none", 10)
    pct = tracker.percentages()
    assert sum(pct.values()) == pytest.approx(100.0, abs=0.2)
    assert pct["none"] == pytest.approx(50.0, abs=0.2)


def test_sin_datos_no_hay_division_por_cero():
    tracker = PossessionTracker()
    assert tracker.share() == {"team_1": 0.0, "team_2": 0.0}
    assert tracker.percentages() == {"team_1": 0.0, "team_2": 0.0, "none": 0.0}


def test_los_segundos_no_dependen_del_numero_de_frames():
    lento = PossessionTracker(confirm_frames=1)
    rapido = PossessionTracker(confirm_frames=1)
    alimentar(lento, "team_1", 10, dt=0.5)     # 10 frames × 0.5 s
    alimentar(rapido, "team_1", 50, dt=0.1)    # 50 frames × 0.1 s
    assert lento.seconds["team_1"] == pytest.approx(rapido.seconds["team_1"])


def test_equipo_desconocido_cuenta_como_sin_dueno():
    tracker = PossessionTracker(confirm_frames=1)
    tracker.update("unknown", 1.0)
    assert tracker.holder == "none"
    assert tracker.seconds["none"] == pytest.approx(1.0)


def test_jugador_mas_cercano_en_pixeles():
    equipo, dist = PossessionTracker.nearest_holder(JUGADORES, (110, 100), threshold=90)
    assert equipo == "team_1"
    assert dist == pytest.approx(10.0)


def test_balon_lejos_de_todos_no_da_posesion():
    equipo, _ = PossessionTracker.nearest_holder(JUGADORES, (2000, 2000), threshold=90)
    assert equipo == "none"


def test_jugador_mas_cercano_en_metros():
    equipo, dist = PossessionTracker.nearest_holder(JUGADORES, (11.0, 10.0), threshold=3.0, use_world=True)
    assert equipo == "team_1"
    assert dist == pytest.approx(1.0)


def test_sin_balon_o_sin_jugadores():
    assert PossessionTracker.nearest_holder(JUGADORES, None, 90)[0] == "none"
    assert PossessionTracker.nearest_holder([], (1, 1), 90)[0] == "none"


def test_jugador_sin_equipo_no_recibe_posesion():
    jugadores = [{"team": "unknown", "center": [100, 100]}]
    assert PossessionTracker.nearest_holder(jugadores, (101, 100), 90)[0] == "none"


def test_snapshot_y_serializacion():
    tracker = PossessionTracker(confirm_frames=2)
    alimentar(tracker, "team_2", 8)
    snapshot = tracker.snapshot()
    assert snapshot["holder"] == "team_2"
    assert set(snapshot) == {"holder", "changes", "seconds", "share", "percentages"}

    restored = PossessionTracker.from_state(tracker.to_state())
    assert restored.seconds == tracker.seconds
    assert restored.holder == tracker.holder
    assert restored.changes == tracker.changes


def test_confirm_frames_invalido():
    with pytest.raises(ValueError):
        PossessionTracker(confirm_frames=0)
