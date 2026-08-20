"""OSNet: la lógica de agrupación, sin PyTorch.

`fcopilot/osnet.py` estaba al 15 % de cobertura. Lo que faltaba no era la red
—esa se prueba pesándola, y CI no puede— sino todo lo que hay **alrededor** de
la red: agrupar embeddings por track, decidir cuándo hay muestras suficientes,
ordenar los clusters de forma determinista y detectar que los dos equipos visten
igual. Eso se prueba inyectando embeddings sintéticos, que es exactamente lo que
la red devolvería.

La regla 7 sigue en pie: aquí no se importa `torch`.
"""

from __future__ import annotations

import numpy as np
import pytest

from fcopilot import osnet as modulo
from fcopilot.osnet import (
    OSNetTeamClassifier,
    SharedOSNetRegistry,
    osnet_weights_available,
)

DIM = 512


def _embedding(semilla: int, cluster: int) -> np.ndarray:
    """Vector unitario de 512-d, separable por cluster y con ruido reproducible."""
    rng = np.random.default_rng(semilla)
    base = np.zeros(DIM)
    base[cluster * 8: cluster * 8 + 8] = 1.0
    vector = base + rng.normal(0, 0.01, DIM)
    return vector / np.linalg.norm(vector)


@pytest.fixture
def clasificador(monkeypatch) -> OSNetTeamClassifier:
    """Clasificador con la red sustituida por embeddings guionizados."""
    # Se construye sin __init__ para no tocar el registro compartido, que
    # intentaría cargar unos pesos que no existen.
    clf = OSNetTeamClassifier.__new__(OSNetTeamClassifier)
    clf.is_fitted = False
    clf.kmeans = None
    clf.weight_path = "pesos-de-mentira.pth"
    clf.min_tracks = 4
    clf.min_frames = 3
    from collections import defaultdict

    clf._embs = defaultdict(list)
    clf._labels = {}
    clf._device = "cpu"
    clf._model = object()          # basta con que no sea None: `available` es True
    return clf


def _alimentar(clf, monkeypatch, tracks_por_cluster=2, frames=3):
    """Da *frames* observaciones a cada track de dos equipos distintos."""
    asignacion = {}
    for cluster in (0, 1):
        for i in range(tracks_por_cluster):
            asignacion[f"c{cluster}_t{i}"] = cluster
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    bbox = (10, 10, 40, 90)
    monkeypatch.setattr(
        OSNetTeamClassifier,
        "_embed",
        lambda self, f, b: _embedding(hash(self._track_actual) % 10_000, asignacion[self._track_actual]),
    )
    etiquetas = {}
    for _ in range(frames):
        for track in asignacion:
            clf._track_actual = track
            etiquetas[track] = clf.predict(frame, bbox, track_id=track)
    return asignacion, etiquetas


# ── Agrupación en dos equipos ───────────────────────────────────────────
def test_dos_kits_distintos_producen_dos_equipos(clasificador, monkeypatch):
    asignacion, _ = _alimentar(clasificador, monkeypatch)
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    finales = {}
    for track in asignacion:
        clasificador._track_actual = track
        finales[track] = clasificador.predict(frame, (10, 10, 40, 90), track_id=track)
    assert clasificador.is_fitted
    equipos = {finales[t] for t in asignacion}
    assert equipos == {"team_1", "team_2"}
    # Y los tracks del mismo kit caen en el mismo equipo.
    por_cluster = {0: set(), 1: set()}
    for track, cluster in asignacion.items():
        por_cluster[cluster].add(finales[track])
    assert len(por_cluster[0]) == 1 and len(por_cluster[1]) == 1
    assert por_cluster[0] != por_cluster[1]


def test_no_agrupa_hasta_tener_tracks_suficientes(clasificador, monkeypatch):
    """min_tracks=4: con dos tracks no hay dos equipos que distinguir."""
    _alimentar(clasificador, monkeypatch, tracks_por_cluster=1, frames=3)
    assert clasificador.is_fitted is False


def test_no_agrupa_hasta_tener_frames_suficientes(clasificador, monkeypatch):
    """min_frames=3: un track visto una vez no vota."""
    _alimentar(clasificador, monkeypatch, tracks_por_cluster=2, frames=2)
    assert clasificador.is_fitted is False


def test_la_etiqueta_de_un_track_no_cambia_una_vez_asignada(clasificador, monkeypatch):
    """Sin esto, un jugador cambiaría de equipo a mitad de partido."""
    asignacion, _ = _alimentar(clasificador, monkeypatch)
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    track = next(iter(asignacion))
    clasificador._track_actual = track
    primera = clasificador.predict(frame, (10, 10, 40, 90), track_id=track)
    for _ in range(20):
        clasificador.predict(frame, (10, 10, 40, 90), track_id=track)
    assert clasificador.predict(frame, (10, 10, 40, 90), track_id=track) == primera


def test_dos_equipos_con_el_mismo_kit_no_se_inventan_una_division(clasificador, monkeypatch):
    """Si todos visten igual, partir en dos produciría etiquetas al azar."""
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    monkeypatch.setattr(OSNetTeamClassifier, "_embed", lambda self, f, b: _embedding(1, 0))
    for _ in range(4):
        for track in ("a", "b", "c", "d"):
            clasificador.predict(frame, (10, 10, 40, 90), track_id=track)
    etiquetas = {clasificador._labels[t] for t in ("a", "b", "c", "d")}
    assert etiquetas == {"team_1"}, "un solo kit debe dar un solo equipo"


def test_el_historial_por_track_esta_acotado(clasificador, monkeypatch):
    """Un partido largo no puede acumular embeddings sin límite."""
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    monkeypatch.setattr(OSNetTeamClassifier, "_embed", lambda self, f, b: _embedding(2, 0))
    for _ in range(50):
        clasificador.predict(frame, (10, 10, 40, 90), track_id="x")
    assert len(clasificador._embs["x"]) <= 30


# ── Camino degradado ────────────────────────────────────────────────────
def test_sin_red_el_clasificador_devuelve_unknown(clasificador, monkeypatch):
    monkeypatch.setattr(OSNetTeamClassifier, "_embed", lambda self, f, b: None)
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    assert clasificador.predict(frame, (10, 10, 40, 90), track_id="x") == "unknown"


def test_sin_red_conserva_la_etiqueta_que_ya_tenia(clasificador, monkeypatch):
    """Perder el embedding de un frame no debe borrar el equipo del jugador."""
    clasificador._labels["x"] = "team_2"
    monkeypatch.setattr(OSNetTeamClassifier, "_embed", lambda self, f, b: None)
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    assert clasificador.predict(frame, (10, 10, 40, 90), track_id="x") == "team_2"


def test_fit_no_hace_nada_porque_el_ajuste_es_incremental(clasificador):
    """Está en la interfaz por compatibilidad con los otros clasificadores."""
    assert clasificador.fit(np.zeros((10, 10, 3), dtype=np.uint8), []) is None


def test_sin_torch_el_registro_no_devuelve_modelo(monkeypatch):
    monkeypatch.setattr(modulo, "TORCH_AVAILABLE", False)
    assert SharedOSNetRegistry().get("pesos.pth") is None


def test_sin_torch_los_pesos_nunca_estan_disponibles(monkeypatch, tmp_path):
    pesos = tmp_path / "osnet.pth"
    pesos.write_bytes(b"no importa")
    monkeypatch.setattr(modulo, "TORCH_AVAILABLE", False)
    assert osnet_weights_available(str(pesos)) is False


def test_unos_pesos_que_no_existen_no_estan_disponibles(monkeypatch):
    monkeypatch.setattr(modulo, "TORCH_AVAILABLE", True)
    assert osnet_weights_available("/no/existe/osnet.pth") is False


def test_el_registro_vacio_no_conoce_ningun_modelo():
    assert SharedOSNetRegistry().stats()["shared_osnet_models"] == 0
