"""Gestor de sesiones: aislamiento, TTL, límite y persistencia."""

import time

import pytest

from fcopilot.sessions import SessionIdError, SessionLimitError, SessionManager, normalize_session_id


class DummyAnalyzer:
    """Analizador mínimo: sólo lo que el gestor necesita."""

    def __init__(self):
        self.state = {"valor": 0}
        self.active_session = None
        self.last_accessed_at = time.time()
        self.frame_count = 0
        self.model_path = "dummy.pt"

    def serialize_state(self):
        return dict(self.state)

    def load_state(self, data):
        self.state = dict(data)

    def touch(self):
        self.last_accessed_at = time.time()

    def is_idle_expired(self, ttl):
        return self.active_session is None and (time.time() - self.last_accessed_at) > ttl

    def session_status(self):
        return {
            "active_session": self.active_session,
            "active_for_s": 0.0,
            "idle_for_s": 0.0,
            "created_at": 0.0,
            "metrics": {},
        }


@pytest.fixture
def manager(tmp_path):
    return SessionManager(state_dir=tmp_path, ttl_seconds=1800, max_sessions=3, analyzer_factory=DummyAnalyzer)


@pytest.mark.parametrize(
    "raw,esperado",
    [(None, "default"), ("", "default"), ("  abc ", "abc"), ("a-b_c9", "a-b_c9")],
)
def test_ids_validos(raw, esperado):
    assert normalize_session_id(raw) == esperado


@pytest.mark.parametrize("raw", ["../etc/passwd", "con espacio", "x" * 65, "a/b", "punto.punto"])
def test_ids_invalidos(raw):
    with pytest.raises(SessionIdError):
        normalize_session_id(raw)


def test_cada_sesion_tiene_su_analizador(manager):
    a, b = manager.get("uno"), manager.get("dos")
    assert a is not b
    assert manager.get("uno") is a


def test_el_estado_se_guarda_y_restaura(manager):
    analyzer = manager.get("partido")
    analyzer.state["valor"] = 42
    assert manager.save("partido", analyzer)
    manager.delete("partido", purge_state=False)
    assert manager.peek("partido") is None
    restaurado = manager.get("partido")
    assert restaurado.state["valor"] == 42


def test_borrar_purga_el_estado(manager):
    analyzer = manager.get("efimera")
    manager.save("efimera", analyzer)
    assert manager.delete("efimera") is True
    assert manager.delete("efimera") is False
    assert manager.get("efimera").state == {"valor": 0}


def test_un_estado_corrupto_no_impide_crear_la_sesion(manager, tmp_path):
    (tmp_path / "rota.json.gz").write_bytes(b"esto no es gzip")
    analyzer = manager.get("rota")
    assert analyzer.state == {"valor": 0}


def test_las_sesiones_ociosas_caducan(tmp_path):
    manager = SessionManager(state_dir=tmp_path, ttl_seconds=0, analyzer_factory=DummyAnalyzer)
    primera = manager.get("x")
    primera.last_accessed_at = time.time() - 10
    assert manager.stats()["cleaned"] == 1
    assert manager.peek("x") is None


def test_al_llegar_al_limite_se_desaloja_la_mas_antigua(manager):
    for i in range(3):
        analyzer = manager.get(f"s{i}")
        analyzer.last_accessed_at = time.time() - (10 - i)
    manager.get("nueva")
    assert manager.peek("s0") is None
    assert manager.peek("nueva") is not None
    assert manager.stats()["count"] == 3


def test_no_se_desaloja_una_sesion_ocupada(tmp_path):
    manager = SessionManager(state_dir=tmp_path, max_sessions=1, analyzer_factory=DummyAnalyzer)
    ocupada = manager.get("trabajando")
    ocupada.active_session = "trabajando:video"
    with pytest.raises(SessionLimitError):
        manager.get("otra")


def test_listado_y_estadisticas(manager):
    manager.get("b")
    manager.get("a")
    ids = [s["session_id"] for s in manager.list_sessions()]
    assert ids == ["a", "b"]
    stats = manager.stats()
    assert stats["count"] == 2 and stats["busy_count"] == 0


def test_shutdown_persiste_todo(manager, tmp_path):
    manager.get("uno").state["valor"] = 7
    manager.shutdown()
    assert (tmp_path / "uno.json.gz").exists()
