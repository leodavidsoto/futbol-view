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


# ── Fuente de tiempo (regla 5) ──────────────────────────────────────────
#
# Ninguna comprobación local puede distinguir el reloj de pared del tiempo de
# vídeo: los dos son monótonos y crecen igual. La única defensa real es declarar
# cuál se usó, impedir mezclarlas y propagar la etiqueta hasta el informe.

from fcopilot.kinematics import TIME_SOURCE_CLOCK, TIME_SOURCE_VIDEO, TimeBaseError


def test_con_timestamp_la_fuente_es_el_video(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(2)])
    resultado = analyzer.process_frame(green_frame, timestamp=0.0)
    assert analyzer.time_source == TIME_SOURCE_VIDEO
    assert resultado["stats"]["time_source"] == TIME_SOURCE_VIDEO


def test_sin_timestamp_la_fuente_es_el_reloj(analyzer, fake_yolo, green_frame):
    """Legítimo en directo, donde no hay tiempo de vídeo que consultar."""
    fake_yolo.set_script([players_row(2)])
    resultado = analyzer.process_frame(green_frame)
    assert analyzer.time_source == TIME_SOURCE_CLOCK
    assert resultado["stats"]["time_source"] == TIME_SOURCE_CLOCK


def test_mezclar_video_y_reloj_es_un_error_ruidoso(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(2)])
    analyzer.process_frame(green_frame, timestamp=0.0)
    with pytest.raises(TimeBaseError, match="video"):
        analyzer.process_frame(green_frame)


def test_mezclar_reloj_y_video_tambien(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(2)])
    analyzer.process_frame(green_frame)
    with pytest.raises(TimeBaseError, match="reloj"):
        analyzer.process_frame(green_frame, timestamp=1.0)


def test_la_fuente_llega_hasta_el_informe(analyzer, fake_yolo, green_frame):
    correr(analyzer, fake_yolo, [players_row(3) + [ball_box(120, 110)]], frames=4, dt=0.1)
    informe = analyzer.get_export(include_positions=False)
    assert informe["meta"]["time_source"] == TIME_SOURCE_VIDEO
    assert "tiempo de vídeo" in informe["meta"]["time_base_note"]


def test_un_informe_de_webcam_queda_etiquetado_como_tal(analyzer, fake_yolo, green_frame):
    """Para que nadie compare métricas de directo con métricas de vídeo."""
    fake_yolo.set_script([players_row(3)])
    for _ in range(3):
        analyzer.process_frame(green_frame)
    informe = analyzer.get_export(include_positions=False)
    assert informe["meta"]["time_source"] == TIME_SOURCE_CLOCK
    assert "sólo comparables" in informe["meta"]["time_base_note"]


def test_reiniciar_la_sesion_permite_cambiar_de_fuente(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(2)])
    analyzer.process_frame(green_frame, timestamp=0.0)
    analyzer.reset()
    assert analyzer.time_source is None
    analyzer.process_frame(green_frame)          # ya no lanza
    assert analyzer.time_source == TIME_SOURCE_CLOCK


def test_la_fuente_sobrevive_a_la_serializacion(analyzer, fake_yolo, green_frame):
    correr(analyzer, fake_yolo, [players_row(2)], frames=3, dt=0.1)
    revivido = FootballAnalyzer({"tracker_type": "simple", "detection_mode": "normal"})
    revivido.load_state(analyzer.serialize_state())
    assert revivido.time_source == TIME_SOURCE_VIDEO
    with pytest.raises(TimeBaseError):
        revivido.process_frame(green_frame)


# ── Cruce de jugadores ──────────────────────────────────────────────────
#
# El caso que rompe todos los trackers y que no estaba probado: dos jugadores
# que se acercan, se cruzan y se separan. Si el tracker les intercambia la
# identidad, las distancias de ambos se disparan y sus equipos bailan.
#
# La velocidad importa: a 3 px por frame y 25 fps son ~34 km/h con la escala por
# defecto de 8 px/m. Un guion más rápido dispara el rechazo de saltos imposibles
# y la prueba mediría eso en vez del cruce.

PASO_PX = 3.0          # ~34 km/h: rápido pero posible
SEPARACION_PX = 180.0  # se cruzan en el frame 30
FRAMES_CRUCE = 40
#: El tracker necesita un frame para confirmar un track nuevo. Ese arranque no
#: forma parte de lo que se está probando.
CALENTAMIENTO = 1


def _cruce(frames: int = FRAMES_CRUCE):
    """Dos jugadores que convergen, se superponen y se separan."""
    guion = []
    for i in range(frames):
        izq = 100.0 + i * PASO_PX
        der = 100.0 + SEPARACION_PX - i * PASO_PX
        guion.append([
            ((izq, 200.0, izq + 24, 260.0), 0.9, 0),
            ((der, 200.0, der + 24, 260.0), 0.9, 0),
        ])
    return guion


def test_dos_jugadores_que_se_cruzan_siguen_siendo_dos(analyzer, fake_yolo, green_frame):
    salida = correr(analyzer, fake_yolo, _cruce(), frames=FRAMES_CRUCE, dt=1 / 25)[CALENTAMIENTO:]
    ids_por_frame = [{p["track_id"] for p in f["players"]} for f in salida]
    assert all(len(ids) == 2 for ids in ids_por_frame), "en algún frame no hubo exactamente dos jugadores"
    assert len(set().union(*ids_por_frame)) == 2, "el tracker inventó identidades nuevas al cruzarse"


def test_las_identidades_no_se_intercambian_al_superponerse(analyzer, fake_yolo, green_frame):
    """El track que iba a la derecha debe seguir yendo a la derecha después del cruce."""
    salida = correr(analyzer, fake_yolo, _cruce(), frames=FRAMES_CRUCE, dt=1 / 25)[CALENTAMIENTO:]
    def x_de(frame):
        return {p["track_id"]: p["center"][0] for p in frame["players"]}
    inicio, fin = x_de(salida[0]), x_de(salida[-1])
    ids = sorted(inicio)
    # El que empezaba más a la izquierda tiene que acabar más a la derecha: se
    # cruzaron. Si el tracker los intercambió, el orden se conserva.
    izquierdo = min(ids, key=lambda t: inicio[t])
    derecho = max(ids, key=lambda t: inicio[t])
    assert fin[izquierdo] > fin[derecho], "las identidades se intercambiaron en el cruce"


def test_un_cruce_no_dispara_las_distancias(analyzer, fake_yolo, green_frame):
    """Un intercambio de identidad se ve como un teletransporte: distancia absurda."""
    correr(analyzer, fake_yolo, _cruce(), frames=FRAMES_CRUCE, dt=1 / 25)
    informe = analyzer.get_export(include_positions=False)
    for jugador in informe["players"]:
        assert jugador["rejected_steps"] == 0, "hubo saltos imposibles: el tracker cambió identidades"
    # Cada uno recorrió lo mismo: la misma distancia en sentidos opuestos.
    distancias = [j["total_dist_m"] for j in informe["players"]]
    assert distancias[0] == pytest.approx(distancias[1], rel=0.05)


def test_un_cruce_no_reasigna_equipos(analyzer, fake_yolo, green_frame):
    """Los equipos manuales son la referencia: si bailan, es el tracker."""
    salida = correr(analyzer, fake_yolo, _cruce(), frames=8, dt=1 / 25)
    ids = sorted({p["track_id"] for f in salida[CALENTAMIENTO:] for p in f["players"]})
    analyzer.update_team(str(ids[0]), "team_1")
    analyzer.update_team(str(ids[1]), "team_2")
    resto = correr(analyzer, fake_yolo, _cruce(), frames=FRAMES_CRUCE, dt=1 / 25)
    for frame in resto:
        equipos = {p["track_id"]: p["team"] for p in frame["players"]}
        assert equipos.get(ids[0]) in (None, "team_1")
        assert equipos.get(ids[1]) in (None, "team_2")


# ── La homografía mapea el suelo, así que se proyectan los pies ──────────
def test_la_posicion_de_campo_sale_de_los_pies_no_del_torso(analyzer, fake_yolo, green_frame):
    """El único punto del jugador que está sobre el plano del suelo es donde pisa.

    Proyectar el centro de la caja —el torso, a ~0,9 m de altura— sitúa al
    jugador varios metros más lejos de la cámara, y el error crece con la
    distancia. Afecta a todo lo que se calcula en metros.
    """
    analyzer.set_homography(IMAGEN, CAMPO)
    caja = (400.0, 200.0, 440.0, 320.0)          # 40x120 px: alto de un jugador
    fake_yolo.set_script([[(caja, 0.9, 0)]] * 3)
    salida = correr(analyzer, fake_yolo, [[(caja, 0.9, 0)]], frames=3, dt=0.1)
    jugador = salida[-1]["players"][0]

    pies = analyzer.pixel_to_world(420.0, 320.0)
    torso = analyzer.pixel_to_world(420.0, 260.0)
    assert jugador["world_pos"] == pytest.approx(list(pies), abs=0.01)
    assert jugador["world_pos"] != pytest.approx(list(torso), abs=0.01)


def test_dos_jugadores_juntos_estan_juntos_en_el_campo(analyzer, fake_yolo, green_frame):
    """Con los pies, dos jugadores lado a lado quedan a metros de distancia
    razonable; con el torso, el de la caja más alta se iba lejos."""
    analyzer.set_homography(IMAGEN, CAMPO)
    guion = [[
        ((400.0, 200.0, 440.0, 320.0), 0.9, 0),   # cerca
        ((460.0, 230.0, 495.0, 320.0), 0.9, 0),   # al lado, caja más corta
    ]]
    salida = correr(analyzer, fake_yolo, guion, frames=3, dt=0.1)
    posiciones = [p["world_pos"] for p in salida[-1]["players"] if p["world_pos"]]
    assert len(posiciones) == 2
    separacion = ((posiciones[0][0] - posiciones[1][0]) ** 2 + (posiciones[0][1] - posiciones[1][1]) ** 2) ** 0.5
    assert separacion < 15.0, f"quedan a {separacion:.1f} m estando pegados en la imagen"
