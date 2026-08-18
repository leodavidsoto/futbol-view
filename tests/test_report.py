"""Informe agregado del partido."""

import pytest

from fcopilot.kinematics import KinematicsConfig, PlayerKinematics, Sample
from fcopilot.possession import PossessionTracker
from fcopilot.report import build_report


def jugador(track_id, nombre, equipo, metros, *, sprint=False):
    config = KinematicsConfig(pixels_per_meter=1.0, smoothing=1.0, min_sprint_s=0.2)
    kin = PlayerKinematics(track_id, config)
    paso = 8.4 if sprint else 1.0    # 30 km/h vs 3.6 km/h
    pasos = max(2, int(metros / paso))
    for i in range(pasos + 1):
        kin.update(Sample(frame=i, t=i * 1.0, x=i * paso, y=0.0))
    kin.finalize()
    return {"name": nombre, "team": equipo, "kinematics": kin}


@pytest.fixture
def informe():
    jugadores = {
        1: jugador(1, "Ana", "team_1", 100),
        2: jugador(2, "Bea", "team_1", 40, sprint=True),
        3: jugador(3, "Cris", "team_2", 60),
    }
    posesion = PossessionTracker(confirm_frames=1)
    for _ in range(30):
        posesion.update("team_1", 0.1)
    for _ in range(10):
        posesion.update("team_2", 0.1)
    return build_report(jugadores, posesion, frames=120, duration_s=60.0, calibrated=True, config={"model": "x.pt"})


def test_bloques_principales(informe):
    assert set(informe) == {"meta", "possession", "teams", "totals", "leaderboards", "players"}
    assert informe["meta"]["frames_analyzed"] == 120
    assert informe["meta"]["calibrated"] is True
    assert informe["meta"]["config"]["model"] == "x.pt"


def test_totales_por_equipo(informe):
    t1 = informe["teams"]["team_1"]
    assert t1["players"] == 2
    assert t1["total_dist_m"] == pytest.approx(
        sum(p["total_dist_m"] for p in informe["players"] if p["team"] == "team_1")
    )
    assert t1["avg_dist_m"] == pytest.approx(t1["total_dist_m"] / 2, abs=0.1)
    assert informe["teams"]["team_2"]["players"] == 1


def test_las_zonas_de_equipo_suman_su_distancia(informe):
    for equipo in ("team_1", "team_2"):
        bloque = informe["teams"][equipo]
        assert sum(bloque["zones_m"].values()) == pytest.approx(bloque["total_dist_m"], abs=0.5)


def test_clasificaciones_ordenadas(informe):
    distancias = [e["value"] for e in informe["leaderboards"]["distance"]]
    assert distancias == sorted(distancias, reverse=True)
    assert informe["leaderboards"]["distance"][0]["name"] == "Ana"
    assert informe["leaderboards"]["sprints"][0]["name"] == "Bea"


def test_posesion_incluida(informe):
    share = informe["possession"]["share"]
    assert share["team_1"] == pytest.approx(75.0, abs=0.1)
    assert share["team_1"] + share["team_2"] == pytest.approx(100.0)


def test_sin_posiciones_el_informe_es_ligero():
    jugadores = {1: jugador(1, "Ana", "team_1", 20)}
    ligero = build_report(jugadores, PossessionTracker(), include_positions=False)
    completo = build_report(jugadores, PossessionTracker(), include_positions=True)
    assert "positions" not in ligero["players"][0]
    assert completo["players"][0]["positions"]


def test_informe_vacio():
    informe = build_report({}, PossessionTracker())
    assert informe["totals"]["players_tracked"] == 0
    assert informe["totals"]["top_speed_kmh"] == 0.0
    assert informe["teams"]["team_1"]["players"] == 0
    assert informe["leaderboards"]["distance"] == []


def test_equipo_sin_jugadores_no_rompe_los_maximos():
    jugadores = {1: jugador(1, "Ana", "team_1", 10)}
    informe = build_report(jugadores, PossessionTracker())
    assert informe["teams"]["team_2"]["top_speed_kmh"] == 0.0
    assert informe["teams"]["team_2"]["zones_m"]["sprint"] == 0.0
