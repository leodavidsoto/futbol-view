"""Pruebas del modelo de carga externa.

Lo que se fija aquí no es «que el código corra», sino las afirmaciones concretas
que un preparador físico leería en el informe y daría por ciertas. Cada prueba
falla si esa afirmación deja de serlo.
"""

from __future__ import annotations

import math

import pytest

from fcopilot.kinematics import SPEED_ZONES, PlayerKinematics, Sample
from fcopilot.load import (
    ACCEL_THRESHOLD_MS2,
    HIGH_INTENSITY_KMH,
    SPEED_BANDS,
    SPRINT_KMH,
    ExternalLoad,
    LoadConfig,
    SquadLoad,
    band_for_speed,
)


def alimentar(carga: ExternalLoad, velocidades_kmh, *, dt=0.2, t0=0.0):
    """Alimenta la carga con un perfil de velocidades crudas.

    Es como la alimenta la cinemática: la distancia de cada tramo se deriva de
    la velocidad, así que el perfil es coherente consigo mismo.
    """
    anterior = None
    t = t0
    for velocidad in velocidades_kmh:
        carga.add_step(
            t_start=t,
            dt_s=dt,
            distance_m=velocidad / 3.6 * dt,
            speed_start_kmh=anterior,
            speed_end_kmh=velocidad,
        )
        anterior = velocidad
        t += dt
    return carga


# ── La tabla de bandas es dato, y tiene que ser coherente ───────────────
def test_los_umbrales_coinciden_con_los_bordes_de_sus_bandas():
    """Mover una banda sin mover su umbral deja el informe contradiciéndose.

    Sin esta prueba, alguien puede cambiar el corte de ``alta_velocidad`` a 15
    km/h y dejar ``HIGH_INTENSITY_KMH`` en 14,4: el informe diría entonces que
    hay 200 m de alta intensidad y 0 m en la banda de alta velocidad.
    """
    bandas = {nombre: (bajo, alto) for nombre, bajo, alto in SPEED_BANDS}
    assert bandas["alta_velocidad"][0] == HIGH_INTENSITY_KMH
    assert bandas["sprint"][0] == SPRINT_KMH


def test_las_bandas_cubren_toda_la_recta_sin_huecos_ni_solapes():
    for (_, _, alto_previo), (_, bajo, _) in zip(SPEED_BANDS, SPEED_BANDS[1:]):
        assert alto_previo == bajo
    assert SPEED_BANDS[0][1] == 0.0
    assert SPEED_BANDS[-1][2] == math.inf


def test_la_cinematica_y_la_carga_comparten_la_misma_tabla():
    """Dos tablas de bandas que dicen lo mismo acaban diciendo cosas distintas.

    Existieron las dos, con cortes diferentes. Esta prueba impide que vuelvan.
    """
    assert SPEED_ZONES is SPEED_BANDS


@pytest.mark.parametrize(
    "velocidad,esperada",
    [
        (0.0, "caminando"),
        (7.19, "caminando"),
        (7.2, "trote"),
        (14.4, "alta_velocidad"),
        (19.8, "muy_alta_velocidad"),
        (25.2, "sprint"),
        (40.0, "sprint"),
    ],
)
def test_el_borde_de_una_banda_pertenece_a_la_banda_de_arriba(velocidad, esperada):
    assert band_for_speed(velocidad) == esperada


# ── Aceleraciones: la métrica más frágil del sistema ────────────────────
def test_el_primer_tramo_no_inventa_una_aceleracion():
    """No saber la velocidad anterior no es lo mismo que saber que era cero.

    Antes de arreglarlo, la primera observación de cada jugador producía una
    aceleración de 25 m/s² —el récord humano ronda 10— porque se comparaba
    contra un cero que nadie había medido.
    """
    carga = ExternalLoad()
    carga.add_step(t_start=0.0, dt_s=0.2, distance_m=1.0, speed_start_kmh=None, speed_end_kmh=18.0)
    assert carga.max_accel_ms2 == 0.0
    assert carga.accelerations == 0
    # La distancia y la banda sí cuentan: el tramo se recorrió de verdad.
    assert carga.band_distance_m["alta_velocidad"] == pytest.approx(1.0)


def test_una_aceleracion_sostenida_por_encima_del_umbral_cuenta():
    carga = ExternalLoad()
    # +0,8 m/s por tramo de 0,2 s = 4 m/s², por encima del umbral de 3.
    escalon_kmh = 0.8 * 3.6
    alimentar(carga, [escalon_kmh * i for i in range(1, 7)])
    carga.finalize()
    assert carga.accelerations == 1
    assert carga.max_accel_ms2 == pytest.approx(0.8 / 0.2, rel=1e-6)


def test_un_pico_mas_corto_que_min_effort_s_no_cuenta():
    """Es la única defensa contra el temblor del tracker; sin ella no hay métrica."""
    carga = ExternalLoad(LoadConfig(min_effort_s=0.5))
    # Un único tramo de 0,2 s por encima del umbral: dura menos de lo exigido.
    carga.add_step(t_start=0.0, dt_s=0.2, distance_m=0.5, speed_start_kmh=5.0, speed_end_kmh=8.0)
    carga.add_step(t_start=0.2, dt_s=0.2, distance_m=0.5, speed_start_kmh=8.0, speed_end_kmh=8.0)
    carga.finalize()
    assert carga.accelerations == 0


def test_la_frenada_se_cuenta_aparte_de_la_aceleracion():
    carga = ExternalLoad()
    subida = [0.8 * 3.6 * i for i in range(1, 7)]
    bajada = list(reversed(subida))
    alimentar(carga, subida + bajada)
    carga.finalize()
    assert carga.accelerations == 1
    assert carga.decelerations == 1
    assert carga.max_decel_ms2 < -ACCEL_THRESHOLD_MS2


# ── Sprints ─────────────────────────────────────────────────────────────
def test_un_sprint_demasiado_corto_en_metros_no_es_un_sprint():
    carga = ExternalLoad(LoadConfig(min_sprint_m=10.0))
    # Un solo tramo a 27 km/h durante 0,4 s recorre 3 m: es un pico, no un sprint.
    alimentar(carga, [27.0, 27.0], dt=0.2)
    carga.finalize()
    assert carga.sprint_count == 0
    # Pero la distancia sí está en la banda de sprint: se recorrió.
    assert carga.band_distance_m["sprint"] > 0


def test_finalize_cierra_el_sprint_con_el_que_termina_el_partido():
    """Es el sprint que más le importa a quien lee el informe."""
    carga = ExternalLoad()
    alimentar(carga, [28.0] * 20)          # 20 tramos de 0,2 s = 4 s a 28 km/h
    assert carga.sprint_count == 0          # sigue abierto
    carga.finalize()
    assert carga.sprint_count == 1


# ── Normalización, que es lo que hace comparables a dos jugadores ───────
def test_los_metros_por_minuto_no_penalizan_al_suplente():
    """Un jugador que entra 10 minutos corre menos y no por eso corre peor."""
    titular = alimentar(ExternalLoad(), [18.0] * 300)     # 60 s observados
    suplente = alimentar(ExternalLoad(), [18.0] * 75)     # 15 s observados
    titular.finalize()
    suplente.finalize()
    assert titular.summary()["total_dist_m"] > suplente.summary()["total_dist_m"]
    assert titular.summary()["per_minute"]["dist_m"] == pytest.approx(
        suplente.summary()["per_minute"]["dist_m"], rel=0.05
    )


def test_las_bandas_suman_la_distancia_total():
    carga = alimentar(ExternalLoad(), [5.0, 12.0, 18.0, 22.0, 30.0] * 10)
    carga.finalize()
    resumen = carga.summary()
    assert sum(resumen["bands_m"].values()) == pytest.approx(resumen["total_dist_m"], abs=0.5)


def test_la_alta_intensidad_es_la_suma_de_las_tres_bandas_superiores():
    carga = alimentar(ExternalLoad(), [5.0, 12.0, 18.0, 22.0, 30.0] * 10)
    carga.finalize()
    resumen = carga.summary()
    superiores = sum(
        resumen["bands_m"][nombre]
        for nombre in ("alta_velocidad", "muy_alta_velocidad", "sprint")
    )
    assert resumen["high_intensity_m"] == pytest.approx(superiores, abs=0.5)


def test_los_umbrales_relativos_salen_del_pico_de_cada_jugador():
    lento = alimentar(ExternalLoad(), [20.0] * 10)
    rapido = alimentar(ExternalLoad(), [32.0] * 10)
    assert lento.relative_thresholds()["sprint_kmh"] == pytest.approx(18.0)
    assert rapido.relative_thresholds()["sprint_kmh"] == pytest.approx(28.8)


# ── Caída de rendimiento: la métrica que responde «¿a quién cambio?» ────
def test_la_caida_se_detecta_cuando_el_jugador_baja_al_final():
    config = LoadConfig(bucket_s=60.0, dropoff_window_s=120.0)
    carga = ExternalLoad(config)
    # 4 minutos fuertes y 2 minutos flojos, un tramo por segundo.
    alimentar(carga, [20.0] * 240, dt=1.0, t0=0.0)
    alimentar(carga, [6.0] * 120, dt=1.0, t0=240.0)
    carga.finalize()
    caida = carga.dropoff()
    assert caida is not None
    assert caida["change_pct"] < -50.0


def test_sin_ventana_de_referencia_la_caida_es_none_y_no_un_cero():
    """Devolver 0 % diría «no ha caído», que es una afirmación que no consta."""
    config = LoadConfig(bucket_s=60.0, dropoff_window_s=300.0)
    carga = alimentar(ExternalLoad(config), [20.0] * 60, dt=1.0)
    carga.finalize()
    assert carga.dropoff() is None


def test_el_perfil_no_deja_huecos_en_los_indices():
    """Un bloque sin actividad se emite a cero: el hueco es información."""
    config = LoadConfig(bucket_s=60.0)
    carga = ExternalLoad(config)
    alimentar(carga, [15.0] * 10, dt=1.0, t0=0.0)
    alimentar(carga, [15.0] * 10, dt=1.0, t0=180.0)   # se salta dos bloques
    perfil = carga.profile()
    assert [p["from_s"] for p in perfil] == [0.0, 60.0, 120.0, 180.0]
    assert perfil[1]["distance_m"] == 0.0


# ── Invariancia al muestreo: la prueba firma de este repositorio ────────
@pytest.mark.parametrize("frame_skip", [0, 2, 5])
def test_la_carga_no_depende_de_cuantos_frames_se_analicen(frame_skip):
    """Analizar 1 de cada N frames no puede cambiar los metros recorridos.

    Es la misma afirmación que ya cazó el fallo de las velocidades ×3, aplicada
    a la carga. Va parametrizada porque con ``frame_skip=0`` pasa igualmente
    aunque el cálculo esté mal.
    """
    paso = frame_skip + 1
    kin = PlayerKinematics(1)
    fps = 25.0
    for frame in range(0, 250, paso):
        t = frame / fps
        kin.update(Sample(frame=frame, t=t, x=0.0, y=0.0, wx=t * 5.0, wy=0.0))
    kin.finalize()
    resumen = kin.summary()["load"]
    assert resumen["total_dist_m"] == pytest.approx(49.0, abs=1.0)
    # 5 m/s = 18 km/h: toda la distancia cae en alta velocidad.
    assert resumen["bands_m"]["alta_velocidad"] == pytest.approx(49.0, abs=1.0)


# ── Persistencia ────────────────────────────────────────────────────────
def test_el_estado_va_y_vuelve_sin_perder_nada():
    carga = alimentar(ExternalLoad(), [5.0, 12.0, 22.0, 30.0, 28.0] * 20)
    carga.finalize()
    restaurada = ExternalLoad.from_state(carga.to_state())
    assert restaurada.summary() == carga.summary()


def test_un_estado_de_la_version_anterior_recupera_al_menos_las_bandas():
    """Una sesión guardada antes de que existiera la carga no puede reventar.

    Lo que no se midió entonces —aceleraciones— arranca a cero en vez de
    inventarse: es lo único honesto que se puede hacer.
    """
    antiguo = {
        "track_id": 7,
        "samples": [],
        "total_distance_m": 120.0,
        "zone_distance_m": {"caminando": 40.0, "trote": 50.0, "alta_velocidad": 30.0},
        "sprints": 2,
    }
    kin = PlayerKinematics.from_state(antiguo)
    assert kin.zone_distance_m["trote"] == 50.0
    assert kin.load.accelerations == 0


# ── Agregado de plantilla ───────────────────────────────────────────────
def test_el_agregado_de_plantilla_promedia_por_jugador():
    escuadra = SquadLoad()
    for metros in (1000.0, 2000.0):
        escuadra.add({"total_dist_m": metros, "high_intensity_m": metros / 10, "sprints": 1,
                      "accelerations": 2, "decelerations": 3, "bands_m": {"trote": metros}})
    datos = escuadra.as_dict()
    assert datos["players"] == 2
    assert datos["total_dist_m"] == pytest.approx(3000.0)
    assert datos["avg_dist_m"] == pytest.approx(1500.0)
    assert datos["accelerations"] == 4


def test_una_plantilla_vacia_no_divide_por_cero():
    assert SquadLoad().as_dict()["avg_dist_m"] == 0.0


# ── Configuración ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "kwargs",
    [
        {"high_intensity_kmh": 0},
        {"sprint_kmh": 5.0},                 # por debajo de alta intensidad
        {"accel_threshold_ms2": 0},
        {"bucket_s": 0},
        {"dropoff_window_s": 0},
        {"relative_sprint_pct": 1.5},
        {"relative_high_pct": 0.0},
    ],
)
def test_una_configuracion_incoherente_se_rechaza_al_construirla(kwargs):
    with pytest.raises(ValueError):
        LoadConfig(**kwargs)


def test_ver_menos_al_jugador_no_es_lo_mismo_que_verle_bajar():
    """La caída se normaliza por tiempo observado, no por metros brutos.

    Un jugador tapado la mitad del tramo final recorre la mitad de metros sin
    haber bajado el ritmo. Comparando sumas brutas saldría un -70 % y el DT
    cambiaría al jugador equivocado; comparando metros por minuto observado sale
    lo que de verdad pasó: nada.

    Esta prueba existe porque la suite pasaba entera con la normalización
    quitada — la primera versión medía las dos ventanas con la misma duración,
    que es precisamente el caso en el que da igual.
    """
    config = LoadConfig(bucket_s=60.0, dropoff_window_s=120.0)
    carga = ExternalLoad(config)
    alimentar(carga, [20.0] * 240, dt=1.0, t0=0.0)      # 4 minutos, vistos enteros
    alimentar(carga, [20.0] * 30, dt=1.0, t0=240.0)     # visto 30 s de este minuto
    alimentar(carga, [20.0] * 30, dt=1.0, t0=300.0)     # y 30 s del siguiente
    alimentar(carga, [20.0] * 5, dt=1.0, t0=355.0)
    carga.finalize()

    caida = carga.dropoff()
    assert caida is not None
    assert caida["recent_hi_m_per_min"] == pytest.approx(caida["baseline_hi_m_per_min"], rel=0.05)
    assert abs(caida["change_pct"]) < 5.0


# ── Cotas de memoria ────────────────────────────────────────────────────
def test_los_bloques_y_los_esfuerzos_estan_acotados():
    """El crecimiento sin tope ya fue un defecto real en este repositorio.

    Un vídeo con marcas de tiempo rotas puede producir bloques en índices
    arbitrarios, y un tracker que tiembla puede producir esfuerzos sin fin. Los
    contadores siguen subiendo —esa información no se pierde—, pero las listas
    y los diccionarios no crecen para siempre.
    """
    carga = ExternalLoad()
    for i in range(ExternalLoad.MAX_BUCKETS + 50):
        carga.add_step(
            t_start=i * 60.0, dt_s=1.0, distance_m=8.0,
            speed_start_kmh=0.0, speed_end_kmh=28.8,
        )
        carga.add_step(
            t_start=i * 60.0 + 1.0, dt_s=1.0, distance_m=0.1,
            speed_start_kmh=28.8, speed_end_kmh=0.0,
        )
    carga.finalize()
    assert len(carga.buckets) <= ExternalLoad.MAX_BUCKETS
    assert len(carga.efforts) <= ExternalLoad.MAX_EFFORTS
    # El contador no se topa: sólo se topa el detalle guardado.
    assert carga.sprint_count > ExternalLoad.MAX_EFFORTS // 3


def test_un_jugador_nunca_visto_no_tiene_perfil_ni_caida():
    carga = ExternalLoad()
    assert carga.profile() == []
    assert carga.dropoff() is None
    assert carga.summary()["per_minute"]["dist_m"] == 0.0
