"""Cinemática: distancia, velocidad, sprints y zonas."""

import math

import pytest

from fcopilot.kinematics import KinematicsConfig, PlayerKinematics, Sample, zone_for_speed


def line_run(kin: PlayerKinematics, *, steps: int, dx_px: float, dt: float, start: float = 0.0) -> None:
    for i in range(steps):
        kin.update(Sample(frame=i, t=start + i * dt, x=i * dx_px, y=0.0))


def test_distancia_no_se_cuenta_dos_veces():
    # 10 pasos de 8 px con 8 px/m ⇒ 10 metros exactos. La versión anterior
    # comparaba con la penúltima muestra y devolvía aproximadamente el doble.
    kin = PlayerKinematics(1, KinematicsConfig(pixels_per_meter=8.0))
    line_run(kin, steps=11, dx_px=8.0, dt=0.5)
    assert kin.total_distance_m == pytest.approx(10.0, abs=1e-6)


def test_velocidad_usa_la_base_de_tiempo_de_la_muestra():
    # 4 m/s = 14.4 km/h, independientemente de a qué ritmo procese el servidor.
    rapido = PlayerKinematics(1, KinematicsConfig(pixels_per_meter=1.0, smoothing=1.0))
    lento = PlayerKinematics(2, KinematicsConfig(pixels_per_meter=1.0, smoothing=1.0))
    for i in range(20):
        rapido.update(Sample(frame=i, t=i * 0.1, x=i * 0.4, y=0.0))
        lento.update(Sample(frame=i, t=i * 0.5, x=i * 2.0, y=0.0))
    assert rapido.speed_kmh == pytest.approx(14.4, abs=0.2)
    assert lento.speed_kmh == pytest.approx(14.4, abs=0.2)


def test_muestras_sin_avance_dan_velocidad_cero():
    kin = PlayerKinematics(1)
    for i in range(10):
        kin.update(Sample(frame=i, t=i * 0.2, x=100.0, y=100.0))
    assert kin.speed_kmh == 0.0
    assert kin.total_distance_m == 0.0


def test_salto_imposible_se_descarta():
    kin = PlayerKinematics(1, KinematicsConfig(pixels_per_meter=1.0, max_speed_kmh=45.0))
    kin.update(Sample(frame=0, t=0.0, x=0.0, y=0.0))
    kin.update(Sample(frame=1, t=0.1, x=3.0, y=0.0))     # 108 km/h → cambio de identidad
    kin.update(Sample(frame=2, t=0.2, x=3.5, y=0.0))
    assert kin.rejected_steps == 1
    assert kin.total_distance_m == pytest.approx(0.5, abs=1e-6)


def test_usa_coordenadas_de_mundo_cuando_hay_homografia():
    kin = PlayerKinematics(1, KinematicsConfig(pixels_per_meter=100.0))
    kin.update(Sample(frame=0, t=0.0, x=0.0, y=0.0, wx=0.0, wy=0.0))
    kin.update(Sample(frame=1, t=1.0, x=1.0, y=0.0, wx=3.0, wy=4.0))
    # 5 m reales, no 0.01 m derivados de la escala en píxeles.
    assert kin.total_distance_m == pytest.approx(5.0)


def test_mezcla_de_muestras_con_y_sin_mundo_no_produce_saltos():
    kin = PlayerKinematics(1, KinematicsConfig(pixels_per_meter=10.0))
    kin.update(Sample(frame=0, t=0.0, x=0.0, y=0.0))
    kin.update(Sample(frame=1, t=1.0, x=10.0, y=0.0, wx=50.0, wy=50.0))
    assert kin.total_distance_m == pytest.approx(1.0)


def test_max_y_media_de_velocidad():
    kin = PlayerKinematics(1, KinematicsConfig(pixels_per_meter=1.0, smoothing=1.0))
    for i in range(10):
        kin.update(Sample(frame=i, t=i * 0.2, x=i * 1.0, y=0.0))
    for i in range(10, 20):
        kin.update(Sample(frame=i, t=i * 0.2, x=10.0, y=0.0))
    assert kin.max_speed_kmh == pytest.approx(18.0, abs=0.5)
    assert kin.speed_kmh == pytest.approx(0.0, abs=0.1)
    assert 0 < kin.avg_speed_kmh <= kin.max_speed_kmh


def test_sprints_requieren_duracion_minima():
    config = KinematicsConfig(pixels_per_meter=1.0, smoothing=1.0, sprint_kmh=25.0, min_sprint_s=0.7)
    kin = PlayerKinematics(1, config)
    t = 0.0
    # 30 km/h ≈ 8.33 m/s durante 1.5 s
    for i in range(16):
        kin.update(Sample(frame=i, t=t, x=t * 8.33, y=0.0))
        t += 0.1
    assert kin.speed_kmh >= 25.0
    for i in range(16, 30):  # frena
        kin.update(Sample(frame=i, t=t, x=16 * 0.1 * 8.33, y=0.0))
        t += 0.1
    assert kin.sprints == 1


def test_finalize_cierra_un_sprint_en_curso():
    config = KinematicsConfig(pixels_per_meter=1.0, smoothing=1.0, min_sprint_s=0.3)
    kin = PlayerKinematics(1, config)
    for i in range(20):
        kin.update(Sample(frame=i, t=i * 0.1, x=i * 0.9, y=0.0))
    assert kin.sprints == 0
    kin.finalize()
    assert kin.sprints == 1
    kin.finalize()  # idempotente
    assert kin.sprints == 1


@pytest.mark.parametrize(
    "speed,zone",
    [(0.0, "caminando"), (6.9, "caminando"), (7.0, "trote"), (15.0, "carrera"),
     (22.0, "alta_intensidad"), (30.0, "sprint")],
)
def test_zonas_de_intensidad(speed, zone):
    assert zone_for_speed(speed) == zone


def test_zonas_reparten_toda_la_distancia():
    kin = PlayerKinematics(1, KinematicsConfig(pixels_per_meter=1.0))
    for i in range(30):
        kin.update(Sample(frame=i, t=i * 0.2, x=i * i * 0.05, y=0.0))
    total_por_zonas = sum(kin.zone_distance_m.values())
    assert total_por_zonas == pytest.approx(kin.total_distance_m, abs=1e-6)


def test_historial_acotado():
    kin = PlayerKinematics(1, KinematicsConfig(max_history=25))
    for i in range(200):
        kin.update(Sample(frame=i, t=i * 0.1, x=i, y=0.0))
    assert len(kin.samples) == 25
    assert len(kin.trail(20)) == 20


def test_serializacion_ida_y_vuelta():
    kin = PlayerKinematics(7, KinematicsConfig(pixels_per_meter=5.0))
    for i in range(12):
        kin.update(Sample(frame=i, t=i * 0.25, x=i * 4.0, y=i * 2.0, wx=i * 0.5, wy=0.0))
    restored = PlayerKinematics.from_state(kin.to_state(), kin.config)
    assert restored.track_id == kin.track_id
    assert restored.total_distance_m == pytest.approx(kin.total_distance_m)
    assert restored.summary() == kin.summary()
    assert len(restored.samples) == len(kin.samples)


def test_config_rechaza_valores_invalidos():
    with pytest.raises(ValueError):
        KinematicsConfig(pixels_per_meter=0)
    with pytest.raises(ValueError):
        KinematicsConfig(smoothing=1.5)
    with pytest.raises(ValueError):
        KinematicsConfig(speed_window_s=0)


def test_resumen_tiene_las_claves_del_informe():
    kin = PlayerKinematics(3)
    kin.update(Sample(frame=0, t=0.0, x=0.0, y=0.0))
    summary = kin.summary()
    assert set(summary) >= {
        "track_id", "total_dist_m", "speed_kmh", "max_speed_kmh",
        "avg_speed_kmh", "sprints", "observed_s", "zones_m",
    }
    assert math.isfinite(summary["total_dist_m"])
