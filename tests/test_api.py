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


# ── Guardia de la regla 6: la sesión es la frontera de aislamiento ───────
#
# Esta es la prueba más importante del carril API y la razón de que exista.
# `AGENTS.md` dice que ninguna ruta accede al estado de una sesión sin pasar por
# la dependencia de sesión, pero eso era una convención: una ruta nueva que
# leyera `session_manager` directamente filtraría datos entre sesiones y ninguna
# prueba lo notaría. Este test recorre las rutas registradas de verdad, así que
# añadir una ruta sin la dependencia rompe la suite en el acto.

from fastapi.routing import APIRoute

import football_copilot_v2_backend as backend

#: Rutas de ámbito global, no de sesión. Cada una está aquí por una razón
#: explícita: si añades una, tienes que justificarla en la misma línea.
RUTAS_SIN_SESION = {
    "/health": "sonda de vida; acepta session_id opcional pero no lo exige",
    "/api/sessions": "lista las sesiones; es administración, no acceso a una",
    "/api/sessions/{session_id}": "el id va en la ruta, que es su propia frontera",
}


def _dependencias_de(route: APIRoute):
    """Nombres de todas las funciones del árbol de dependencias de una ruta."""
    nombres, pendientes = set(), [route.dependant]
    while pendientes:
        dep = pendientes.pop()
        if dep.call is not None:
            nombres.add(getattr(dep.call, "__name__", ""))
        pendientes.extend(dep.dependencies)
    return nombres


def _rutas_de_api():
    return [
        r for r in backend.app.routes
        if isinstance(r, APIRoute) and (r.path.startswith("/api") or r.path == "/health")
    ]


def test_toda_ruta_de_sesion_declara_la_dependencia_de_sesion():
    sin_guardia = []
    for route in _rutas_de_api():
        if route.path in RUTAS_SIN_SESION:
            continue
        if "get_session_id" not in _dependencias_de(route):
            sin_guardia.append(f"{sorted(route.methods)} {route.path}")
    assert not sin_guardia, (
        "estas rutas llegan al estado sin pasar por la dependencia de sesión, "
        f"así que pueden filtrar datos entre sesiones: {sin_guardia}. "
        "Añade `session_id: str = Depends(get_session_id)` o justifica la excepción "
        "en RUTAS_SIN_SESION."
    )


def test_la_lista_de_excepciones_no_se_ha_quedado_obsoleta():
    """Una excepción para una ruta que ya no existe esconde la siguiente."""
    existentes = {r.path for r in backend.app.routes if isinstance(r, APIRoute)}
    huerfanas = set(RUTAS_SIN_SESION) - existentes
    assert not huerfanas, f"excepciones para rutas inexistentes: {sorted(huerfanas)}"


def test_hay_rutas_que_auditar():
    """Si el descubrimiento se rompe, la auditoría pasaría vacía y sin avisar."""
    assert len(_rutas_de_api()) >= 10


def test_una_sesion_no_ve_los_datos_de_otra(client, fake_yolo):
    fake_yolo.set_script([[]])
    client.post("/api/player-name", json={"track_id": "1", "name": "Messi"}, headers={"x-session-id": "partido-a"})
    ajena = client.get("/api/export", headers={"x-session-id": "partido-b"}).json()
    nombres = {j["name"] for j in ajena.get("players", [])}
    assert "Messi" not in nombres


# ── Credencial opcional (R-27) ──────────────────────────────────────────
#
# A-01 sigue sin responder: no se sabe si esto se expone o corre en local. La
# autenticación se implementa y viene APAGADA, para no romper el uso local y que
# encenderla sea una variable de entorno en vez de un desarrollo.

import pytest


@pytest.fixture
def con_credencial(monkeypatch):
    monkeypatch.setattr(backend, "API_KEY", "secreto-de-prueba")
    return "secreto-de-prueba"


def test_sin_credencial_configurada_el_servicio_esta_abierto(client):
    assert client.get("/api/config").status_code == 200


def test_con_credencial_una_peticion_sin_ella_es_401(client, con_credencial):
    assert client.get("/api/config").status_code == 401


def test_con_credencial_correcta_se_pasa(client, con_credencial):
    respuesta = client.get("/api/config", headers={"x-api-key": con_credencial})
    assert respuesta.status_code == 200


def test_una_credencial_equivocada_es_401(client, con_credencial):
    assert client.get("/api/config", headers={"x-api-key": "otra"}).status_code == 401


def test_un_prefijo_de_la_credencial_no_cuela(client, con_credencial):
    """La comparación es en tiempo constante; esto fija que no sea por prefijo."""
    assert client.get("/api/config", headers={"x-api-key": "secreto"}).status_code == 401


def test_la_credencial_tambien_vale_por_query_string(client, con_credencial):
    """El WebSocket y las descargas del navegador no pueden poner cabeceras."""
    assert client.get(f"/api/config?api_key={con_credencial}").status_code == 200


def test_health_sigue_abierto_con_credencial(client, con_credencial):
    """Una sonda de vida que exige credencial no sirve de sonda de vida."""
    assert client.get("/health").status_code == 200


def test_health_declara_si_el_servicio_esta_autenticado(client):
    limites = client.get("/health").json()["limits"]
    assert limites["auth_required"] is False
    assert limites["max_concurrent_analyses"] >= 1
    assert "cors_any_origin" in limites


def test_toda_ruta_de_api_queda_cubierta_por_el_middleware(client, con_credencial):
    """Se protege por middleware y no ruta a ruta: una ruta nueva ya viene cubierta."""
    abiertas = []
    for route in _rutas_de_api():
        if route.path in ("/health",) or "{" in route.path:
            continue
        metodo = "GET" if "GET" in route.methods else sorted(route.methods)[0]
        respuesta = client.request(metodo, route.path)
        if respuesta.status_code != 401:
            abiertas.append(f"{metodo} {route.path} -> {respuesta.status_code}")
    assert not abiertas, f"rutas que no exigen credencial teniéndola configurada: {abiertas}"


# ── Límite de análisis simultáneos (R-28) ───────────────────────────────
def test_sin_plazas_libres_la_subida_es_429(client, fake_yolo, monkeypatch):
    """Doce sesiones subiendo a la vez ocupan doce temporales y dos hilos."""
    import threading

    monkeypatch.setattr(backend, "analysis_slots", threading.BoundedSemaphore(1))
    backend.analysis_slots.acquire()
    respuesta = client.post(
        "/api/process-video",
        files={"file": ("p.mp4", b"contenido", "video/mp4")},
        headers={"x-session-id": "una"},
    )
    assert respuesta.status_code == 429
    assert "analizando" in respuesta.json()["detail"]


def test_una_plaza_ocupada_se_devuelve_si_falla_la_subida(client, fake_yolo, monkeypatch):
    """Si no se liberara, un fallo de subida agotaría las plazas para siempre."""
    import threading

    semaforo = threading.BoundedSemaphore(1)
    monkeypatch.setattr(backend, "analysis_slots", semaforo)
    client.post(
        "/api/process-video",
        files={"file": ("p.txt", b"no es video", "text/plain")},
        headers={"x-session-id": "una"},
    )
    assert semaforo.acquire(blocking=False), "la plaza no se devolvió"


# ── Resolución de análisis (R-21) ───────────────────────────────────────
#
# `process_width`/`process_height` estaban en los defaults y validados en
# `fcopilot.config`, pero faltaban en el esquema de la API: el backend los
# rechazaba con 422 y nadie podía salir de 854x480. En tomas elevadas y anchas,
# donde los jugadores ocupan pocos píxeles, esa reducción se come las
# detecciones antes de que el detector las vea.

def test_la_resolucion_de_analisis_se_puede_cambiar(client):
    respuesta = client.post("/api/config", json={"process_width": 1920, "process_height": 1080})
    assert respuesta.status_code == 200, respuesta.text
    config = client.get("/api/config").json()
    assert config["process_width"] == 1920
    assert config["process_height"] == 1080


def test_una_resolucion_fuera_de_rango_se_rechaza(client):
    assert client.post("/api/config", json={"process_width": 99}).status_code == 400
    assert client.post("/api/config", json={"process_height": 4000}).status_code == 400


#: Claves que a propósito NO se pueden cambiar por la API, cada una con su
#: motivo en la misma línea. Una excepción sin motivo escrito es la forma en que
#: esta comprobación se vacía con el tiempo.
CLAVES_NO_EXPUESTAS = {
    "osnet_weight_path": (
        "es una ruta del sistema de ficheros a un .pth, que es un pickle: "
        "cargarlo ejecuta código. `model_path` sí se expone porque pasa por "
        "validate_model_path; esta no tiene equivalente, así que se configura "
        "por variable de entorno y no por petición HTTP"
    ),
}


def test_toda_clave_de_configuracion_es_alcanzable_desde_la_api():
    """El esquema de la API y los defaults no pueden divergir en silencio.

    Es el fallo que hubo con `process_width`/`process_height`: existían en los
    defaults, se validaban en `fcopilot.config`, y el esquema de la API los
    rechazaba con 422. En la práctica no existían, y nadie podía salir de la
    resolución de análisis por defecto.
    """
    from fcopilot.config import DEFAULTS

    campos = set(backend.ConfigRequest.model_fields)
    campos.discard("model")          # se llama `model_path` en los defaults
    campos.add("model_path")
    inalcanzables = set(DEFAULTS) - campos - set(CLAVES_NO_EXPUESTAS)
    assert not inalcanzables, (
        f"claves de configuración que nadie puede cambiar por la API: {sorted(inalcanzables)}. "
        "Añádelas a ConfigRequest, o a CLAVES_NO_EXPUESTAS con el motivo."
    )


def test_toda_clave_no_expuesta_tiene_su_motivo_escrito():
    from fcopilot.config import DEFAULTS

    for clave, motivo in CLAVES_NO_EXPUESTAS.items():
        assert clave in DEFAULTS, f"{clave} ya no existe: quítala de la lista"
        assert len(motivo) > 40, f"{clave}: el motivo tiene que explicar, no etiquetar"


# ── Zona de juego ───────────────────────────────────────────────────────
CAMPO_TRAPECIO = [[400, 200], [1500, 200], [1700, 600], [200, 600]]


def test_definir_la_zona_de_juego(client):
    r = client.post("/api/play-area", json={"points": CAMPO_TRAPECIO})
    assert r.status_code == 200 and r.json()["vertices"] == 4
    zona = client.get("/api/play-area").json()
    assert zona["defined"] is True and len(zona["points"]) == 4


def test_sin_definirla_no_hay_zona(client):
    assert client.get("/api/play-area").json()["defined"] is False


def test_borrar_la_zona(client):
    client.post("/api/play-area", json={"points": CAMPO_TRAPECIO})
    assert client.delete("/api/play-area").json()["defined"] is False
    assert client.get("/api/play-area").json()["defined"] is False


def test_un_triangulo_vale_como_zona(client):
    r = client.post("/api/play-area", json={"points": [[0, 0], [500, 0], [250, 400]]})
    assert r.status_code == 200


def test_dos_vertices_no_delimitan_nada(client):
    assert client.post("/api/play-area", json={"points": [[0, 0], [100, 100]]}).status_code == 422


def test_una_zona_degenerada_es_400_con_el_motivo(client):
    r = client.post("/api/play-area", json={"points": [[0, 0], [1, 1], [2, 2], [3, 3]]})
    assert r.status_code == 400
    assert "degenerada" in r.json()["detail"]


def test_un_vertice_mal_formado_es_400(client):
    r = client.post("/api/play-area", json={"points": [[0, 0], [1, 1, 1], [2, 2]]})
    assert r.status_code == 400


def test_la_zona_es_por_sesion(client):
    """Como todo lo demás: el campo de un partido no es el de otro."""
    client.post("/api/play-area", json={"points": CAMPO_TRAPECIO}, headers={"x-session-id": "partido-a"})
    ajena = client.get("/api/play-area", headers={"x-session-id": "partido-b"}).json()
    assert ajena["defined"] is False


def test_el_websocket_rechaza_antes_de_crear_la_sesion(client, con_credencial, monkeypatch):
    """Sin esto, una conexión sin credencial construye un analizador entero
    —modelo incluido— y, con MAX_SESSIONS al límite, desaloja la sesión de otro.
    """
    creadas = []
    original = client.session_manager.get
    monkeypatch.setattr(
        client.session_manager, "get",
        lambda sid, *a, **k: (creadas.append(sid), original(sid, *a, **k))[1],
    )
    with client.websocket_connect("/ws/stream?session_id=intruso") as ws:
        mensaje = json.loads(ws.receive_text())
    assert "credencial" in mensaje["error"]
    assert creadas == [], f"se creó la sesión {creadas} antes de comprobar la credencial"


def test_el_websocket_acepta_con_credencial(client, con_credencial):
    with client.websocket_connect(f"/ws/stream?session_id=ok&api_key={con_credencial}") as ws:
        ws.close()
