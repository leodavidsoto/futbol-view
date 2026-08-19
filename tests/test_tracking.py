"""Tracker de respaldo: identidades estables, oclusiones y limpieza."""

import pytest

from fcopilot.tracking import SimpleCentroidTracker, bbox_center


def box(x, y, w=20, h=40):
    return [x, y, x + w, y + h]


def test_centro_de_la_caja():
    assert bbox_center([0, 0, 10, 20]) == (5.0, 10.0)
    assert bbox_center([10, 10, 20, 20]) == (15.0, 15.0)


def test_las_identidades_se_mantienen_entre_frames():
    tracker = SimpleCentroidTracker(distance_threshold=40, min_hits=1)
    tracker.update([box(0, 0), box(200, 0)])
    primeros = {tid for tid, *_ in tracker.update([box(5, 0), box(205, 0)])}
    segundos = {tid for tid, *_ in tracker.update([box(10, 0), box(210, 0)])}
    assert primeros == segundos == {1, 2}


def test_min_hits_evita_ids_por_ruido():
    tracker = SimpleCentroidTracker(distance_threshold=40, min_hits=2)
    assert tracker.update([box(0, 0)]) == []
    salida = tracker.update([box(3, 0)])
    assert [tid for tid, *_ in salida] == [1]


def test_una_deteccion_lejana_crea_un_track_nuevo():
    tracker = SimpleCentroidTracker(distance_threshold=30, min_hits=1)
    tracker.update([box(0, 0)])
    salida = tracker.update([box(500, 0)])
    assert [tid for tid, *_ in salida] == [2]


def test_track_perdido_sobrevive_una_oclusion_corta():
    tracker = SimpleCentroidTracker(distance_threshold=40, max_missing=3, min_hits=1)
    tracker.update([box(0, 0)])
    tracker.update([box(10, 0)])
    assert tracker.update([]) == []              # oclusión
    recuperado = tracker.update([box(30, 0)])    # reaparece donde se predijo
    assert [tid for tid, *_ in recuperado] == [1]


def test_track_se_elimina_tras_demasiadas_ausencias():
    tracker = SimpleCentroidTracker(distance_threshold=40, max_missing=2, min_hits=1)
    tracker.update([box(0, 0)])
    for _ in range(4):
        tracker.update([])
    assert tracker.active_tracks == 0
    assert [tid for tid, *_ in tracker.update([box(0, 0)])] == [2]


def test_prediccion_con_velocidad_constante():
    tracker = SimpleCentroidTracker(distance_threshold=15, min_hits=1)
    tracker.update([box(0, 0)])
    for i in range(1, 6):
        salida = tracker.update([box(i * 12, 0)])
    # 12 px por frame supera el umbral estático, pero no el predicho.
    assert [tid for tid, *_ in salida] == [1]


def test_asignacion_uno_a_uno_con_jugadores_juntos():
    tracker = SimpleCentroidTracker(distance_threshold=60, min_hits=1)
    tracker.update([box(100, 0), box(140, 0)])
    salida = tracker.update([box(105, 0), box(145, 0)])
    assert sorted(tid for tid, *_ in salida) == [1, 2]
    assert len({tid for tid, *_ in salida}) == 2


def test_reset_y_parametros_invalidos():
    tracker = SimpleCentroidTracker(min_hits=1)
    tracker.update([box(0, 0)])
    tracker.reset()
    assert tracker.active_tracks == 0
    assert [tid for tid, *_ in tracker.update([box(0, 0)])] == [1]

    with pytest.raises(ValueError):
        SimpleCentroidTracker(distance_threshold=0)
    with pytest.raises(ValueError):
        SimpleCentroidTracker(max_missing=-1)


def test_devuelve_las_cajas_observadas():
    tracker = SimpleCentroidTracker(min_hits=1)
    tracker.update([box(10, 20)])
    salida = tracker.update([box(12, 22)])
    assert salida[0][1:] == (12.0, 22.0, 32.0, 62.0)


def test_las_detecciones_mas_fiables_reciben_los_ids_bajos():
    tracker = SimpleCentroidTracker(min_hits=1)
    salida = tracker.update([box(0, 0), box(300, 0)], [0.2, 0.95])
    ids = {tuple(caja[1:3]): caja[0] for caja in salida}
    assert ids[(300.0, 0.0)] < ids[(0.0, 0.0)]
