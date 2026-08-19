"""Pruebas de la fusión de tracklets.

Lo que hay que fijar aquí es que la fusión **no cosa dos jugadores distintos**.
Fusionar de menos deja el problema como estaba; fusionar de más produce un
jugador inventado con las métricas de dos, y eso es peor que no fusionar nada.
Casi todas las pruebas de este fichero son de lo segundo.
"""

from __future__ import annotations

import numpy as np
import pytest

from fcopilot.tracklets import (
    MergeConfig,
    Tracklet,
    TrackletError,
    cosine_similarity,
    merge_tracklets,
)


def trozo(
    track_id: int,
    t0: float,
    t1: float,
    xy0=(0.0, 0.0),
    xy1=None,
    *,
    v=(0.0, 0.0),
    embedding=None,
    team="unknown",
    team_confidence=0.0,
    samples=10,
) -> Tracklet:
    return Tracklet(
        track_id=track_id,
        first_t=t0,
        last_t=t1,
        first_xy=xy0,
        last_xy=xy1 if xy1 is not None else xy0,
        last_velocity=v,
        embedding=embedding,
        team=team,
        team_confidence=team_confidence,
        samples=samples,
    )


# ── El caso que motiva el módulo ────────────────────────────────────────
def test_un_jugador_partido_en_tres_trozos_vuelve_a_ser_uno():
    """Es el defecto medido: 51 identidades para ~22 jugadores."""
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0), v=(2.0, 0.0)),
        trozo(2, 5.6, 10.0, (11.2, 0.0), (20.0, 0.0), v=(2.0, 0.0)),
        trozo(3, 10.5, 15.0, (21.0, 0.0), (30.0, 0.0), v=(2.0, 0.0)),
    ]
    resultado = merge_tracklets(tracklets)
    assert resultado.identities_before == 3
    assert resultado.identities_after == 1
    assert set(resultado.mapping.values()) == {1}
    # Los dos trozos que arrancan tras un hueco quedan marcados.
    assert sorted(resultado.discontinuities) == [2, 3]


def test_el_mapa_siempre_se_puede_aplicar():
    """Un track que no se fusiona se mapea a sí mismo; nadie se queda fuera."""
    tracklets = [trozo(7, 0.0, 1.0), trozo(9, 50.0, 51.0, (500.0, 500.0))]
    resultado = merge_tracklets(tracklets)
    assert resultado.mapping == {7: 7, 9: 9}
    assert resultado.identities_after == 2


# ── Lo que NUNCA debe fusionarse ────────────────────────────────────────
def test_dos_trozos_que_coexisten_no_son_el_mismo_jugador():
    """Nadie está en dos sitios a la vez, por mucho que se parezcan."""
    tracklets = [
        trozo(1, 0.0, 10.0, (0.0, 0.0), (1.0, 0.0)),
        trozo(2, 5.0, 15.0, (1.1, 0.0), (2.0, 0.0)),   # solapa 5 s
    ]
    resultado = merge_tracklets(tracklets)
    assert resultado.identities_after == 2


def test_un_hueco_que_exigiria_correr_a_100_kmh_se_rechaza():
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0)),
        trozo(2, 5.5, 10.0, (90.0, 0.0)),               # 80 m en medio segundo
    ]
    resultado = merge_tracklets(tracklets)
    assert resultado.identities_after == 2
    assert resultado.rejected >= 1


def test_un_hueco_demasiado_largo_se_rechaza_aunque_este_al_lado():
    """En ocho segundos cualquier compañero con la misma camiseta encaja igual."""
    config = MergeConfig(max_gap_s=3.0)
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0)),
        trozo(2, 12.0, 15.0, (10.2, 0.0)),
    ]
    assert merge_tracklets(tracklets, config).identities_after == 2


def test_dos_equipos_distintos_con_confianza_vetan_la_fusion():
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0), team="team_1", team_confidence=0.9),
        trozo(2, 5.2, 10.0, (10.3, 0.0), team="team_2", team_confidence=0.9),
    ]
    assert merge_tracklets(tracklets).identities_after == 2


def test_un_equipo_desconocido_no_veta_a_nadie():
    """Vetar por 'unknown' impediría justo las fusiones que más falta hacen.

    En los primeros frames de un track el clasificador aún no tiene votos, así
    que el trozo nuevo casi siempre llega sin equipo.
    """
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0), team="team_1", team_confidence=0.9),
        trozo(2, 5.2, 10.0, (10.3, 0.0), team="unknown"),
    ]
    assert merge_tracklets(tracklets).identities_after == 1


def test_un_equipo_asignado_con_poca_confianza_no_veta():
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0), team="team_1", team_confidence=0.9),
        trozo(2, 5.2, 10.0, (10.3, 0.0), team="team_2", team_confidence=0.2),
    ]
    assert merge_tracklets(tracklets).identities_after == 1


def test_dos_apariencias_distintas_no_se_cosen():
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0), embedding=np.array([1.0, 0.0, 0.0])),
        trozo(2, 5.2, 10.0, (10.3, 0.0), embedding=np.array([0.0, 1.0, 0.0])),
    ]
    assert merge_tracklets(tracklets).identities_after == 2


def test_dos_jugadores_no_pueden_coserse_al_mismo_trozo():
    """Cada trozo tiene como mucho un sucesor: si no, dos jugadores se funden.

    Los dos candidatos son físicamente admisibles; sólo uno puede ganar.
    """
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0)),
        trozo(2, 5.2, 9.0, (10.2, 0.0)),      # más cerca: debería ganar
        trozo(3, 5.2, 9.0, (11.5, 0.0)),
    ]
    resultado = merge_tracklets(tracklets)
    assert resultado.identities_after == 2
    assert resultado.mapping[2] == 1
    assert resultado.mapping[3] == 3


# ── Extrapolación ───────────────────────────────────────────────────────
def test_la_prediccion_usa_la_velocidad_del_jugador():
    """Un jugador en carrera reaparece por delante, no donde se le perdió."""
    config = MergeConfig(slack=0.5)
    corriendo = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0), v=(6.0, 0.0)),
        trozo(2, 6.0, 9.0, (16.0, 0.0)),      # justo donde le lleva su velocidad
    ]
    assert merge_tracklets(corriendo, config).identities_after == 1


def test_un_trozo_de_una_sola_muestra_no_extrapola():
    """Con una muestra no hay velocidad; usarla sería extrapolar ruido."""
    config = MergeConfig(slack=0.5, max_speed_kmh=15.0)
    tracklets = [
        trozo(1, 0.0, 0.0, (0.0, 0.0), (0.0, 0.0), v=(50.0, 0.0), samples=1),
        trozo(2, 1.0, 5.0, (50.0, 0.0)),
    ]
    # Con la velocidad falsa habría encajado; sin extrapolar, 50 m en 1 s no.
    assert merge_tracklets(tracklets, config).identities_after == 2


# ── Unidades ────────────────────────────────────────────────────────────
def test_en_pixeles_el_radio_se_traduce_con_la_escala():
    """Un radio de metros aplicado a píxeles rechazaría casi todo."""
    en_metros = MergeConfig(units="m", slack=0.0)
    en_pixeles = MergeConfig(units="px", pixels_per_meter=10.0, slack=0.0)
    # 20 m/s durante 1 s = 20 m = 200 px con esta escala.
    tracklets_px = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (100.0, 0.0)),
        trozo(2, 6.0, 9.0, (180.0, 0.0)),
    ]
    assert merge_tracklets(tracklets_px, en_pixeles).identities_after == 1
    assert merge_tracklets(tracklets_px, en_metros).identities_after == 2


# ── Similitud de coseno ─────────────────────────────────────────────────
def test_sin_descriptor_la_similitud_es_none_y_no_cero():
    """Cero diría «no se parecen»; None dice «no se puede juzgar»."""
    assert cosine_similarity(None, np.array([1.0, 0.0])) is None
    assert cosine_similarity(np.array([0.0, 0.0]), np.array([1.0, 0.0])) is None
    assert cosine_similarity(np.array([1.0, 0.0]), np.array([1.0, 0.0, 0.0])) is None
    assert cosine_similarity(np.array([1.0, 0.0]), np.array([2.0, 0.0])) == pytest.approx(1.0)


def test_sin_apariencia_la_fusion_sigue_siendo_posible_por_fisica():
    """Sin OSNet no se puede dejar de fusionar: es el caso normal en CPU."""
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0)),
        trozo(2, 5.2, 10.0, (10.3, 0.0)),
    ]
    assert merge_tracklets(tracklets).identities_after == 1


def test_a_igualdad_de_distancia_gana_el_que_se_parece():
    """La apariencia desempata; si no, la elección sería arbitraria."""
    aspecto = np.array([1.0, 0.0, 0.0])
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0), embedding=aspecto),
        trozo(2, 5.2, 9.0, (10.5, 0.0)),                              # sin descriptor
        trozo(3, 5.2, 9.0, (10.5, 0.0), embedding=aspecto),           # idéntico
    ]
    resultado = merge_tracklets(tracklets)
    assert resultado.mapping[3] == 1
    assert resultado.mapping[2] == 2


# ── Determinismo y robustez ─────────────────────────────────────────────
def test_el_resultado_no_depende_del_orden_de_entrada():
    tracklets = [
        trozo(1, 0.0, 5.0, (0.0, 0.0), (10.0, 0.0)),
        trozo(2, 5.3, 10.0, (10.5, 0.0), (20.0, 0.0)),
        trozo(3, 20.0, 25.0, (60.0, 30.0)),
    ]
    directo = merge_tracklets(tracklets).mapping
    invertido = merge_tracklets(list(reversed(tracklets))).mapping
    assert directo == invertido


def test_dos_tracklets_con_el_mismo_id_se_rechazan_diciendolo():
    with pytest.raises(TrackletError) as exc:
        merge_tracklets([trozo(1, 0.0, 1.0), trozo(1, 2.0, 3.0)])
    assert "1" in str(exc.value)


def test_un_tracklet_que_termina_antes_de_empezar_se_rechaza():
    with pytest.raises(TrackletError):
        Tracklet(track_id=1, first_t=5.0, last_t=1.0, first_xy=(0, 0), last_xy=(0, 0))


def test_una_lista_vacia_no_revienta():
    resultado = merge_tracklets([])
    assert resultado.mapping == {}
    assert resultado.identities_after == 0


@pytest.mark.parametrize(
    "kwargs",
    [{"units": "leguas"}, {"max_gap_s": 0}, {"max_speed_kmh": 0},
     {"min_similarity": 2.0}, {"pixels_per_meter": 0}],
)
def test_una_configuracion_incoherente_se_rechaza(kwargs):
    with pytest.raises(TrackletError):
        MergeConfig(**kwargs)


def test_el_resumen_dice_cuanto_se_redujo_la_fragmentacion():
    """Es el número que hay que poder mirar para saber si esto sirve de algo."""
    tracklets = [
        trozo(i, i * 2.0, i * 2.0 + 1.5, (i * 4.0, 0.0), (i * 4.0 + 3.0, 0.0), v=(2.0, 0.0))
        for i in range(6)
    ]
    resumen = merge_tracklets(tracklets).summary()
    assert resumen["identities_before"] == 6
    assert resumen["identities_after"] < 6
    assert resumen["merged"] == 6 - resumen["identities_after"]
    assert len(resumen["detail"]) == resumen["merged"]


def test_una_cadena_no_se_muerde_la_cola():
    """Todos los eslabones apuntan a la raíz, no al anterior."""
    tracklets = [
        trozo(i, i * 3.0, i * 3.0 + 2.5, (i * 5.0, 0.0), (i * 5.0 + 4.0, 0.0), v=(1.6, 0.0))
        for i in range(1, 5)
    ]
    mapa = merge_tracklets(tracklets).mapping
    assert set(mapa.values()) == {1}
    assert all(mapa[v] == v for v in mapa.values())


def test_saltarse_un_trozo_nunca_sale_mas_barato_que_el_eslabon_contiguo():
    """El coste tenía sesgo a favor de los huecos largos, y era grave.

    La distancia se normalizaba por un radio que **crece con el hueco**, así que
    el mismo error absoluto salía más barato cuanto más lejos estuviera el
    candidato. Con cuatro trozos consecutivos de un mismo jugador, la fusión
    producía las cadenas 1→3 y 2→4 en vez de 1→2→3→4: dos jugadores donde había
    uno, cada uno con la mitad de los metros, y ninguna señal de que algo
    hubiera ido mal.
    """
    tracklets = [
        trozo(1, 0.0, 2.0, (0.0, 0.0), (4.0, 0.0), v=(2.0, 0.0)),
        trozo(2, 2.5, 4.5, (5.0, 0.0), (9.0, 0.0), v=(2.0, 0.0)),
        trozo(3, 5.0, 7.0, (10.0, 0.0), (14.0, 0.0), v=(2.0, 0.0)),
        trozo(4, 7.5, 9.5, (15.0, 0.0), (19.0, 0.0), v=(2.0, 0.0)),
    ]
    resultado = merge_tracklets(tracklets)
    assert resultado.identities_after == 1
    # Y las uniones son las contiguas, no las salteadas.
    assert {(m.head_id, m.tail_id) for m in resultado.merges} == {(1, 2), (2, 3), (3, 4)}
