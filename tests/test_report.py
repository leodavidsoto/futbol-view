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


# ── Carga externa en el informe ─────────────────────────────────────────
def _jugador_con_carga(track_id: int, team: str, velocidad_kmh: float, pasos: int = 60):
    """Un jugador que corre en línea recta a velocidad constante."""
    from fcopilot.kinematics import PlayerKinematics, Sample

    kin = PlayerKinematics(track_id)
    dt = 0.2
    for i in range(pasos):
        t = i * dt
        kin.update(Sample(frame=i, t=t, x=0.0, y=0.0, wx=t * velocidad_kmh / 3.6, wy=0.0))
    kin.finalize()
    return {"kinematics": kin, "name": f"J{track_id}", "team": team}


def test_el_total_del_equipo_es_la_suma_de_sus_jugadores():
    """Si el bloque de equipo tuviera su propio bucle, podría dejar de cuadrar.

    El agregado lo hace ``SquadLoad``, el mismo que suma en cualquier otro sitio.
    Esta prueba es la que impide que alguien reescriba el bucle "para que sea
    más rápido" y produzca un informe en el que el equipo no suma sus partes.
    """
    from fcopilot.possession import PossessionTracker

    jugadores = {
        1: _jugador_con_carga(1, "team_1", 18.0),
        2: _jugador_con_carga(2, "team_1", 22.0),
        3: _jugador_con_carga(3, "team_2", 10.0),
    }
    informe = build_report(jugadores, PossessionTracker(), include_positions=False)

    for equipo in ("team_1", "team_2"):
        suma = sum(
            j["load"]["total_dist_m"] for j in informe["players"] if j["team"] == equipo
        )
        assert informe["teams"][equipo]["total_dist_m"] == pytest.approx(suma, abs=0.2)


def test_la_distancia_de_carga_y_la_de_cinematica_no_se_separan():
    """Son dos acumuladores del mismo recorrido; divergir sería un fallo mudo."""
    from fcopilot.possession import PossessionTracker

    jugadores = {1: _jugador_con_carga(1, "team_1", 19.0)}
    informe = build_report(jugadores, PossessionTracker(), include_positions=False)
    jugador = informe["players"][0]
    assert jugador["load"]["total_dist_m"] == pytest.approx(jugador["total_dist_m"], abs=0.2)


def test_el_ranking_por_minuto_premia_al_que_mas_corre_no_al_que_mas_juega():
    """Es la diferencia entre medir esfuerzo y medir permanencia.

    Los dos jugadores están observados por encima del mínimo para extrapolar
    (``min_observed_s_for_rates``) a propósito. La primera versión de esta
    prueba usaba un «suplente» de ocho segundos, y ése no tiene tasa por minuto
    en absoluto: extrapolar un minuto desde ocho segundos no es medir. Lo que
    la prueba quiere comparar —ritmo frente a permanencia— sigue igual.
    """
    from fcopilot.possession import PossessionTracker

    jugadores = {
        1: _jugador_con_carga(1, "team_1", 16.0, pasos=500),   # 100 s, ritmo bajo
        2: _jugador_con_carga(2, "team_1", 24.0, pasos=200),   # 40 s, ritmo alto
    }
    informe = build_report(jugadores, PossessionTracker(), include_positions=False)
    assert informe["leaderboards"]["distance"][0]["track_id"] == 1
    assert informe["leaderboards"]["intensity_per_min"][0]["track_id"] == 2


def test_quien_se_vio_dos_segundos_no_entra_en_un_ranking_de_tasas():
    """Ponerle un 0 sería injusto y ponerle su tasa cruda le haría el primero."""
    from fcopilot.possession import PossessionTracker

    jugadores = {
        1: _jugador_con_carga(1, "team_1", 16.0, pasos=500),   # 100 s
        2: _jugador_con_carga(2, "team_1", 30.0, pasos=10),    # 2 s a toda velocidad
    }
    informe = build_report(jugadores, PossessionTracker(), include_positions=False)
    ranking = informe["leaderboards"]["intensity_per_min"]
    assert [e["track_id"] for e in ranking] == [1]
    # Pero sus metros, que sí se midieron, siguen contando en los totales.
    assert informe["totals"]["total_dist_m"] > 0


def test_un_equipo_sin_jugadores_da_ceros_y_no_revienta():
    from fcopilot.possession import PossessionTracker

    informe = build_report({}, PossessionTracker(), include_positions=False)
    assert informe["teams"]["team_1"]["players"] == 0
    assert informe["teams"]["team_1"]["avg_dist_m"] == 0.0
    assert informe["totals"]["accelerations"] == 0
