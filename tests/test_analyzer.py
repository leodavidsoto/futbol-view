"""Analizador completo con un detector guionizado."""

import numpy as np
import pytest

from conftest import ball_box, players_row
from fcopilot.analyzer import FootballAnalyzer, resolve_tracker_type
from fcopilot.detection import DetectorUnavailable, shared_yolo_registry
from fcopilot.geometry import CalibrationError

CAMPO = [[0.0, 0.0], [105.0, 0.0], [105.0, 68.0], [0.0, 68.0]]
IMAGEN = [[0.0, 0.0], [854.0, 0.0], [854.0, 480.0], [0.0, 480.0]]


def correr(analyzer, fake_yolo, guion, frames, dt):
    """Ejecuta *frames* frames con el guion dado y una base de tiempo fija."""
    fake_yolo.set_script(guion)
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    salida = []
    for i in range(frames):
        salida.append(analyzer.process_frame(frame, timestamp=i * dt))
    return salida


def test_estructura_de_la_respuesta(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(4) + [ball_box(120, 110)]])
    resultado = analyzer.process_frame(green_frame, timestamp=0.0)
    assert set(resultado) >= {"frame", "t", "fps", "players", "ball", "stats", "timings_ms", "possession"}
    assert resultado["frame"] == 1
    assert resultado["stats"]["tracker"] == "simple"
    jugador = resultado["players"][0] if resultado["players"] else None
    if jugador:
        assert set(jugador) >= {"track_id", "name", "team", "bbox", "center", "speed_kmh", "total_dist_m", "trail"}


def test_la_velocidad_no_depende_del_muestreo(fake_yolo):
    """El mismo movimiento medido cada 1/30 s y cada 1/10 s da la misma velocidad."""
    velocidades = []
    for dt, factor in ((1 / 30, 1), (1 / 10, 3)):
        analyzer = FootballAnalyzer({"tracker_type": "simple", "detection_mode": "normal"})
        analyzer.pixels_per_meter = 10.0
        guion = [players_row(1, dx=i * 2.0 * factor) for i in range(40)]
        salida = correr(analyzer, fake_yolo, guion, frames=40, dt=dt)
        jugadores = salida[-1]["players"]
        assert jugadores, "el tracker deberia haber confirmado al jugador"
        velocidades.append(jugadores[0]["speed_kmh"])
    assert velocidades[0] == pytest.approx(velocidades[1], rel=0.05)


def test_la_distancia_se_acumula_en_metros(fake_yolo):
    analyzer = FootballAnalyzer({"tracker_type": "simple", "detection_mode": "normal"})
    analyzer.pixels_per_meter = 10.0
    guion = [players_row(1, dx=i * 10.0) for i in range(21)]   # 10 px = 1 m por frame
    salida = correr(analyzer, fake_yolo, guion, frames=21, dt=0.5)
    jugador = salida[-1]["players"][0]
    # El track se confirma en el segundo frame, así que se miden 19 tramos.
    assert jugador["total_dist_m"] == pytest.approx(19.0, abs=0.5)


def test_la_homografia_produce_coordenadas_de_campo(analyzer, fake_yolo, green_frame):
    analyzer.set_homography(IMAGEN, CAMPO)
    assert analyzer.is_calibrated
    fake_yolo.set_script([players_row(2)])
    analyzer.process_frame(green_frame, timestamp=0.0)
    resultado = analyzer.process_frame(green_frame, timestamp=0.1)
    for jugador in resultado["players"]:
        assert jugador["world_pos"] is not None
        x, y = jugador["world_pos"]
        assert 0 <= x <= 105 and 0 <= y <= 68


def test_calibracion_invalida(analyzer):
    with pytest.raises(CalibrationError):
        analyzer.set_homography([[0, 0], [1, 1], [2, 2], [3, 3]], CAMPO)
    assert not analyzer.is_calibrated


def test_posesion_para_el_equipo_mas_cercano(analyzer, fake_yolo, green_frame):
    analyzer.update_team("1", "team_1")
    analyzer.update_team("2", "team_2")
    guion = [players_row(2, x0=50, step=400) + [ball_box(60, 110)] for _ in range(8)]
    salida = correr(analyzer, fake_yolo, guion, frames=8, dt=0.1)
    ultimo = salida[-1]
    assert ultimo["ball"] is not None
    assert ultimo["ball"]["possession"] == "team_1"
    assert ultimo["ball"]["possession_pct"]["team_1"] > ultimo["ball"]["possession_pct"]["team_2"]


def test_sin_balon_no_hay_posesion(analyzer, fake_yolo, green_frame):
    salida = correr(analyzer, fake_yolo, [players_row(3) for _ in range(4)], frames=4, dt=0.1)
    assert salida[-1]["ball"] is None
    assert analyzer.possession.seconds["none"] > 0


def test_el_equipo_manual_gana_al_clasificador(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(3) for _ in range(3)])
    analyzer.process_frame(green_frame, timestamp=0.0)
    analyzer.update_team("1", "team_2")
    resultado = analyzer.process_frame(green_frame, timestamp=0.1)
    jugador = next((p for p in resultado["players"] if p["track_id"] == 1), None)
    assert jugador is not None and jugador["team"] == "team_2"


def test_los_nombres_se_propagan(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(2) for _ in range(3)])
    analyzer.process_frame(green_frame, timestamp=0.0)
    analyzer.update_name("1", "Maestre")
    resultado = analyzer.process_frame(green_frame, timestamp=0.1)
    assert any(p["name"] == "Maestre" for p in resultado["players"])


def test_timestamps_que_retroceden_no_rompen_las_metricas(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(2) for _ in range(4)])
    analyzer.process_frame(green_frame, timestamp=10.0)
    analyzer.process_frame(green_frame, timestamp=11.0)
    resultado = analyzer.process_frame(green_frame, timestamp=3.0)   # el usuario rebobina
    assert resultado["t"] >= 0
    for jugador in resultado["players"]:
        assert jugador["speed_kmh"] >= 0
        assert jugador["total_dist_m"] >= 0


def test_soft_reset_conserva_las_asignaciones(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(2) for _ in range(2)])
    analyzer.process_frame(green_frame, timestamp=0.0)
    analyzer.update_team("1", "team_1")
    analyzer.update_name("1", "Capitán")
    analyzer.soft_reset()
    assert analyzer.frame_count == 0
    assert analyzer.tracks == {}
    assert analyzer.player_teams == {"1": "team_1"}
    assert analyzer.player_names == {"1": "Capitán"}


def test_reset_completo_borra_todo(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(2)])
    analyzer.process_frame(green_frame, timestamp=0.0)
    analyzer.update_team("1", "team_1")
    analyzer.reset()
    assert analyzer.player_teams == {} and analyzer.player_names == {}
    assert analyzer.possession.total_seconds == 0


def test_informe_del_partido(analyzer, fake_yolo, green_frame):
    analyzer.update_team("1", "team_1")
    analyzer.update_team("2", "team_2")
    guion = [players_row(2, step=300, dx=i * 6.0) + [ball_box(60 + i * 6.0, 110)] for i in range(20)]
    correr(analyzer, fake_yolo, guion, frames=20, dt=0.2)
    informe = analyzer.get_export()
    assert informe["meta"]["frames_analyzed"] == 20
    assert informe["totals"]["players_tracked"] >= 2
    assert informe["teams"]["team_1"]["players"] >= 1
    assert informe["possession"]["share"]["team_1"] + informe["possession"]["share"]["team_2"] == pytest.approx(100.0)
    assert informe["players"][0]["positions"]

    ligero = analyzer.get_export(include_positions=False)
    assert "positions" not in ligero["players"][0]


def test_serializacion_ida_y_vuelta(analyzer, fake_yolo, green_frame):
    analyzer.set_homography(IMAGEN, CAMPO)
    analyzer.pixels_per_meter = 12.5
    guion = [players_row(2, dx=i * 5.0) + [ball_box(60, 110)] for i in range(10)]
    correr(analyzer, fake_yolo, guion, frames=10, dt=0.2)
    estado = analyzer.serialize_state()

    import json

    estado = json.loads(json.dumps(estado))   # debe ser serializable a JSON
    restaurado = FootballAnalyzer({"tracker_type": "simple", "detection_mode": "normal"})
    restaurado.load_state(estado)

    assert restaurado.frame_count == analyzer.frame_count
    assert restaurado.pixels_per_meter == pytest.approx(12.5)
    assert restaurado.is_calibrated
    assert set(restaurado.tracks) == set(analyzer.tracks)
    for tid, track in restaurado.tracks.items():
        assert track["kinematics"].summary() == analyzer.tracks[tid]["kinematics"].summary()
    assert restaurado.possession.seconds == analyzer.possession.seconds


def test_apply_config_reinicia_lo_necesario(analyzer):
    resultado = analyzer.apply_config({"norfair_dist": 80, "confidence": 0.3})
    assert resultado["tracker_reinited"] is True
    assert resultado["model_reloaded"] is False
    assert analyzer.config["confidence"] == 0.3

    resultado = analyzer.apply_config({"confidence": 0.25})
    assert resultado["tracker_reinited"] is False


def test_cambiar_de_clasificador(analyzer):
    resultado = analyzer.apply_config({"team_classifier": "grass_kmeans"})
    assert resultado["classifier_reinited"] is True
    assert analyzer.team_clf.name == "grass_kmeans"


def test_las_metricas_de_tiempo_se_promedian(analyzer, fake_yolo, green_frame):
    correr(analyzer, fake_yolo, [players_row(2) for _ in range(5)], frames=5, dt=0.1)
    assert analyzer.metrics["frames_processed"] == 5
    assert analyzer.metrics["avg_total_ms"] >= 0
    assert analyzer.metrics["last_total_ms"] >= 0


def test_tracker_elegido_segun_disponibilidad():
    assert resolve_tracker_type("simple") == "simple"
    # Sin norfair ni supervision instalados se degrada al de respaldo.
    assert resolve_tracker_type("desconocido") in {"simple", "norfair", "bytetrack"}


def test_sin_detector_falla_al_construir():
    shared_yolo_registry.clear()
    from fcopilot.detection import YOLO_AVAILABLE

    if YOLO_AVAILABLE:  # pragma: no cover - entorno con ultralytics
        pytest.skip("ultralytics instalado: el registro cargaria el modelo real")
    with pytest.raises(DetectorUnavailable):
        FootballAnalyzer({"tracker_type": "simple"})
