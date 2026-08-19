"""Endpoints HTTP y WebSocket."""

import json

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from conftest import ball_box, players_row

HEADERS = {"x-session-id": "test"}
CAMPO = [[0, 0], [105, 0], [105, 68], [0, 68]]
IMAGEN = [[0, 0], [854, 0], [854, 480], [0, 480]]


def jpeg_frame(color=(40, 140, 40)) -> bytes:
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    frame[:, :] = color
    return cv2.imencode(".jpg", frame)[1].tobytes()


def video_bytes(frames=12, size=(854, 480)) -> bytes:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clip.mp4"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25.0, size)
        for i in range(frames):
            frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
            frame[:, :] = (40, 140, 40)
            frame[100:160, 50 + i * 5: 74 + i * 5] = (200, 60, 40)
            writer.write(frame)
        writer.release()
        return path.read_bytes()


# ── Salud y sesiones ─────────────────────────────────────────────────────
def test_health(client):
    data = client.get("/health").json()
    assert data["status"] == "ok"
    assert set(data["capabilities"]) >= {"yolo", "sahi", "norfair", "bytetrack", "torch", "opencv"}
    assert data["sessions"]["count"] >= 0


def test_health_no_crea_sesiones(client):
    client.get("/health?session_id=fantasma")
    assert client.session_manager.peek("fantasma") is None


def test_health_con_sesion_existente(client):
    client.get("/api/config", headers=HEADERS)
    data = client.get("/health?session_id=test").json()
    assert data["session_id"] == "test"
    assert data["model"] is not None


def test_listado_y_borrado_de_sesiones(client):
    client.get("/api/config", headers=HEADERS)
    assert any(s["session_id"] == "test" for s in client.get("/api/sessions").json()["sessions"])
    assert client.delete("/api/sessions/test").json()["ok"] is True
    assert client.delete("/api/sessions/test").status_code == 404


def test_session_id_invalido(client):
    assert client.get("/api/config", headers={"x-session-id": "mala sesion"}).status_code == 400
    assert client.delete("/api/sessions/mala%20sesion").status_code == 400


def test_las_sesiones_estan_aisladas(client):
    client.post("/api/player-name", json={"track_id": "1", "name": "Ana"}, headers={"x-session-id": "a"})
    export_b = client.get("/api/export", headers={"x-session-id": "b"}).json()
    assert export_b["totals"]["players_tracked"] == 0


def test_limite_de_sesiones(client):
    for i in range(3):
        assert client.get("/api/config", headers={"x-session-id": f"s{i}"}).status_code == 200
    # El gestor desaloja la más antigua en lugar de rechazar la petición.
    assert client.get("/api/config", headers={"x-session-id": "s3"}).status_code == 200


# ── Configuración ────────────────────────────────────────────────────────
def test_get_config(client):
    data = client.get("/api/config", headers=HEADERS).json()
    assert data["tracker_effective"] in {"simple", "norfair", "bytetrack"}
    assert "sahi_available" in data and "osnet_available" in data


def test_post_config_valido(client):
    resp = client.post("/api/config", json={"confidence": 0.35, "imgsz": 640}, headers=HEADERS)
    assert resp.status_code == 200 and resp.json()["ok"] is True
    data = client.get("/api/config", headers=HEADERS).json()
    assert data["confidence"] == 0.35 and data["imgsz"] == 640


@pytest.mark.parametrize(
    "payload",
    [{"imgsz": 99}, {"confidence": 2}, {"detection_mode": "magia"}, {"tracker_type": "deepsort"}, {"frame_skip": -1}],
)
def test_post_config_invalido(client, payload):
    assert client.post("/api/config", json=payload, headers=HEADERS).status_code in (400, 422)


def test_config_rechaza_claves_desconocidas(client):
    assert client.post("/api/config", json={"rm_rf": True}, headers=HEADERS).status_code == 422


def test_no_se_puede_cargar_un_modelo_de_fuera_del_proyecto(client):
    resp = client.post("/api/config", json={"model": "/etc/passwd"}, headers=HEADERS)
    assert resp.status_code == 400
    resp = client.post("/api/config", json={"model": "/tmp/evil.pt"}, headers=HEADERS)
    assert resp.status_code == 400


def test_modo_no_disponible_se_rechaza(client):
    from fcopilot.detection import SAHI_AVAILABLE

    resp = client.post("/api/config", json={"detection_mode": "sahi"}, headers=HEADERS)
    assert resp.status_code == (200 if SAHI_AVAILABLE else 400)


# ── Jugadores ────────────────────────────────────────────────────────────
def test_nombre_y_equipo_de_jugador(client):
    assert client.post("/api/player-name", json={"track_id": "3", "name": " Maestre "}, headers=HEADERS).status_code == 200
    assert client.post("/api/player-team", json={"track_id": "3", "team": "team_2"}, headers=HEADERS).status_code == 200
    analyzer = client.session_manager.peek("test")
    assert analyzer.player_names["3"] == "Maestre"
    assert analyzer.player_teams["3"] == "team_2"


@pytest.mark.parametrize(
    "payload,ruta",
    [
        ({"track_id": "1", "name": ""}, "/api/player-name"),
        ({"track_id": "1", "name": "x" * 100}, "/api/player-name"),
        ({"track_id": "1", "team": "team_9"}, "/api/player-team"),
        ({"track_id": "1"}, "/api/player-team"),
    ],
)
def test_payloads_invalidos(client, payload, ruta):
    assert client.post(ruta, json=payload, headers=HEADERS).status_code == 422


# ── Calibración ──────────────────────────────────────────────────────────
def test_calibracion_por_escala(client):
    resp = client.post("/api/calibrate", json={"pixels_per_meter": 12.5}, headers=HEADERS)
    assert resp.json() == {"ok": True, "mode": "scale", "pixels_per_meter": 12.5}
    assert client.get("/api/calibrate", headers=HEADERS).json()["pixels_per_meter"] == 12.5


def test_calibracion_por_homografia(client):
    resp = client.post("/api/calibrate", json={"img_points": IMAGEN, "world_points": CAMPO}, headers=HEADERS)
    assert resp.json()["mode"] == "homography"
    assert client.get("/api/calibrate", headers=HEADERS).json()["calibrated"] is True
    assert client.delete("/api/calibrate", headers=HEADERS).json()["calibrated"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"img_points": IMAGEN},
        {"img_points": IMAGEN[:3], "world_points": CAMPO[:3]},
        {"img_points": [[0, 0, 0]] * 4, "world_points": CAMPO},
        {"img_points": [[0, 0], [1, 1], [2, 2], [3, 3]], "world_points": CAMPO},
    ],
)
def test_calibracion_invalida(client, payload):
    assert client.post("/api/calibrate", json=payload, headers=HEADERS).status_code == 400


# ── Preview / export / reset ─────────────────────────────────────────────
def test_preview_frame(client, fake_yolo):
    fake_yolo.set_script([players_row(4) + [ball_box(120, 110)]])
    resp = client.post(
        "/api/preview-frame",
        files={"frame": ("f.jpg", jpeg_frame(), "image/jpeg")},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["frame"] == 1 and "players" in data


def test_preview_frame_rechaza_formatos(client):
    resp = client.post(
        "/api/preview-frame",
        files={"frame": ("f.txt", b"hola", "text/plain")},
        headers=HEADERS,
    )
    assert resp.status_code == 415


def test_preview_frame_con_imagen_corrupta(client):
    resp = client.post(
        "/api/preview-frame",
        files={"frame": ("f.jpg", b"no soy un jpeg", "image/jpeg")},
        headers=HEADERS,
    )
    assert resp.status_code == 400


def test_preview_frame_vacio(client):
    resp = client.post("/api/preview-frame", files={"frame": ("f.jpg", b"", "image/jpeg")}, headers=HEADERS)
    assert resp.status_code == 400


def test_export_y_report(client, fake_yolo):
    fake_yolo.set_script([players_row(3)])
    client.post("/api/preview-frame", files={"frame": ("f.jpg", jpeg_frame(), "image/jpeg")}, headers=HEADERS)
    export = client.get("/api/export", headers=HEADERS).json()
    assert set(export) == {"meta", "possession", "teams", "totals", "leaderboards", "players"}
    report = client.get("/api/report", headers=HEADERS).json()
    assert all("positions" not in p for p in report["players"])


def test_reset(client, fake_yolo):
    client.post("/api/player-team", json={"track_id": "1", "team": "team_1"}, headers=HEADERS)
    client.post("/api/reset?soft=true", headers=HEADERS)
    assert client.session_manager.peek("test").player_teams == {"1": "team_1"}
    client.post("/api/reset", headers=HEADERS)
    assert client.session_manager.peek("test").player_teams == {}


# ── Vídeo ────────────────────────────────────────────────────────────────
def test_process_video_devuelve_ndjson(client, fake_yolo):
    fake_yolo.set_script([players_row(3, dx=i * 4.0) + [ball_box(60 + i * 4.0, 110)] for i in range(30)])
    resp = client.post(
        "/api/process-video",
        files={"file": ("clip.mp4", video_bytes(), "video/mp4")},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    lineas = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    assert lineas, "el analisis no produjo frames"
    assert all("video_time" in l for l in lineas)
    # El tiempo de vídeo avanza de forma monótona y coherente con 25 fps.
    tiempos = [l["video_time"] for l in lineas]
    assert tiempos == sorted(tiempos)
    assert tiempos[0] > 0


def test_process_video_rechaza_otros_tipos(client):
    resp = client.post(
        "/api/process-video",
        files={"file": ("x.txt", b"hola", "text/plain")},
        headers=HEADERS,
    )
    assert resp.status_code == 415


def test_process_video_con_datos_ilegibles(client):
    resp = client.post(
        "/api/process-video",
        files={"file": ("roto.mp4", b"esto no es un video", "video/mp4")},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    primera = json.loads(resp.text.strip().split("\n")[0])
    assert "error" in primera


def test_el_analizador_queda_libre_tras_el_video(client, fake_yolo):
    fake_yolo.set_script([players_row(2)])
    client.post(
        "/api/process-video",
        files={"file": ("clip.mp4", video_bytes(frames=6), "video/mp4")},
        headers=HEADERS,
    )
    assert client.session_manager.peek("test").active_session is None


def test_limite_de_subida(client, monkeypatch):
    import football_copilot_v2_backend as backend

    monkeypatch.setattr(backend, "MAX_UPLOAD_MB", 0)
    resp = client.post(
        "/api/preview-frame",
        files={"frame": ("f.jpg", jpeg_frame(), "image/jpeg")},
        headers=HEADERS,
    )
    assert resp.status_code == 413


# ── WebSocket ────────────────────────────────────────────────────────────
def test_websocket_procesa_frames(client, fake_yolo):
    fake_yolo.set_script([players_row(3) + [ball_box(120, 110)]])
    with client.websocket_connect("/ws/stream?session_id=live") as ws:
        ws.send_bytes(jpeg_frame())
        data = json.loads(ws.receive_text())
        assert data["frame"] == 1
        assert "players" in data


def test_websocket_con_frame_ilegible(client, fake_yolo):
    with client.websocket_connect("/ws/stream?session_id=live") as ws:
        ws.send_bytes(b"basura")
        assert "error" in json.loads(ws.receive_text())


def test_websocket_rechaza_session_id_invalido(client):
    with client.websocket_connect("/ws/stream?session_id=mala%20sesion") as ws:
        assert "error" in json.loads(ws.receive_text())
