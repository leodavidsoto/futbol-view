"""Pruebas del panel del director técnico.

Lo que hay que fijar aquí no es el formato, es el juicio: que el panel **avise
cuando no se puede creer a sí mismo**, y que el semáforo señale a quien hay que
señalar y no a quien no.
"""

from __future__ import annotations

import pytest

from fcopilot.dashboard import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    STATUS_OK,
    STATUS_SUBSTITUTE,
    STATUS_WATCH,
    DashboardConfig,
    Quality,
    build_dashboard,
)


def jugador(
    track_id: int,
    *,
    team="team_1",
    minutos=60.0,
    hi_por_min=40.0,
    caida=None,
    dist=8000.0,
    sprints=10,
    punta=30.0,
):
    return {
        "track_id": track_id,
        "name": f"J{track_id}",
        "team": team,
        "max_speed_kmh": punta,
        "total_dist_m": dist,
        "sprints": sprints,
        "load": {
            "total_dist_m": dist,
            "high_intensity_m": hi_por_min * minutos,
            "sprints": sprints,
            "accelerations": 20,
            "decelerations": 18,
            "observed_s": minutos * 60.0,
            "bands_m": {"caminando": dist * 0.4, "trote": dist * 0.4},
            "per_minute": {"dist_m": dist / minutos, "high_intensity_m": hi_por_min},
            "dropoff": None if caida is None else {"change_pct": caida},
        },
    }


def informe(jugadores, *, calibrado=True, minutos=90.0, time_source="video"):
    return {
        "meta": {
            "exported_at": "2026-08-19T21:00:00",
            "duration_s": minutos * 60.0,
            "calibrated": calibrado,
            "distance_unit": "m" if calibrado else "m (estimado por escala px/m)",
            "time_source": time_source,
            "frames_analyzed": 5000,
        },
        "totals": {"players_tracked": len(jugadores), "rejected_steps": 3},
        "possession": {"team_1": 52.0, "team_2": 48.0},
        "teams": {"team_1": {"players": len(jugadores)}, "team_2": {"players": 0}},
        "players": jugadores,
    }


def calidad_buena(**kwargs):
    base = dict(
        calibrated=True, time_source="video", players_tracked=22,
        identities_before_merge=24, rejected_steps=3, frames_analyzed=5000,
        frames_with_ball=4000, pitch_name="futbol_11", pitch_source="reglamento",
    )
    base.update(kwargs)
    return Quality(**base)


# ── Lo primero: ¿se puede creer al panel? ───────────────────────────────
def test_sin_calibracion_la_confianza_es_baja_y_lo_dice():
    """Las cifras siguen siendo bonitas y ya no son metros. Callarlo es mentir."""
    panel = build_dashboard(
        informe([jugador(1)], calibrado=False),
        calidad_buena(calibrated=False),
    )
    assert panel["quality"]["confidence"] == CONFIDENCE_LOW
    codigos = [a["code"] for a in panel["quality"]["warnings"]]
    assert "sin_calibrar" in codigos
    mensaje = next(a for a in panel["quality"]["warnings"] if a["code"] == "sin_calibrar")
    # El aviso dice qué cifra deja de valer, no sólo qué pasó.
    assert "distancias" in mensaje["message"]


def test_una_fragmentacion_alta_desaconseja_usar_la_tabla():
    """Un jugador contado tres veces reparte entre tres lo que hizo uno."""
    panel = build_dashboard(
        informe([jugador(1)]),
        calidad_buena(players_tracked=22, identities_before_merge=51),
    )
    assert panel["quality"]["fragmentation"] == pytest.approx(2.32, abs=0.01)
    aviso = next(a for a in panel["quality"]["warnings"] if a["code"] == "fragmentacion")
    assert aviso["level"] == "critico"
    assert panel["quality"]["confidence"] == CONFIDENCE_LOW


def test_sin_fusion_no_se_supone_que_la_fragmentacion_fue_buena():
    """No saber cuántas identidades se crearon no es saber que fue una por jugador."""
    panel = build_dashboard(
        informe([jugador(1)]), calidad_buena(identities_before_merge=None)
    )
    assert panel["quality"]["fragmentation"] is None
    assert "sin_fusion" in [a["code"] for a in panel["quality"]["warnings"]]


def test_un_panel_impecable_no_inventa_avisos():
    panel = build_dashboard(informe([jugador(1)]), calidad_buena())
    assert panel["quality"]["warnings"] == []
    assert panel["quality"]["confidence"] == CONFIDENCE_HIGH


def test_las_metricas_de_reloj_se_marcan_como_no_comparables():
    panel = build_dashboard(
        informe([jugador(1)], time_source="reloj"),
        calidad_buena(time_source="reloj"),
    )
    assert "reloj" in [a["code"] for a in panel["quality"]["warnings"]]
    assert panel["quality"]["confidence"] == CONFIDENCE_MEDIUM


def test_un_balon_poco_visto_desacredita_la_posesion():
    panel = build_dashboard(
        informe([jugador(1)]),
        calidad_buena(frames_with_ball=500, frames_analyzed=5000),
    )
    aviso = next(a for a in panel["quality"]["warnings"] if a["code"] == "balon")
    assert "posesión" in aviso["message"].lower() or "posesion" in aviso["message"].lower()


def test_un_campo_escalado_avisa_de_que_las_marcas_son_aproximadas():
    panel = build_dashboard(informe([jugador(1)]), calidad_buena(pitch_source="escalado"))
    assert "campo_escalado" in [a["code"] for a in panel["quality"]["warnings"]]


# ── El semáforo ─────────────────────────────────────────────────────────
def test_una_caida_grande_propone_el_cambio_y_explica_por_que():
    panel = build_dashboard(informe([jugador(1, caida=-35.0)]), calidad_buena())
    fila = panel["players"][0]
    assert fila["status"] == STATUS_SUBSTITUTE
    assert "35" in fila["detail"]


def test_una_caida_moderada_solo_pide_vigilar():
    panel = build_dashboard(informe([jugador(1, caida=-18.0)]), calidad_buena())
    assert panel["players"][0]["status"] == STATUS_WATCH


def test_un_jugador_que_mantiene_el_ritmo_no_se_señala():
    panel = build_dashboard(informe([jugador(1, caida=-3.0)]), calidad_buena())
    assert panel["players"][0]["status"] == STATUS_OK
    assert panel["attention"] == []


def test_un_jugador_recien_entrado_no_se_juzga_por_su_caida():
    """Con pocos minutos la ventana de referencia es ruido, no rendimiento.

    Sin esta regla, cada suplente aparecería en rojo nada más entrar.
    """
    panel = build_dashboard(informe([jugador(1, minutos=5.0, caida=-60.0)]), calidad_buena())
    assert panel["players"][0]["status"] == STATUS_OK


def test_correr_mucho_menos_que_su_equipo_se_señala_aunque_no_haya_caido():
    """Un jugador puede ir flojo todo el partido sin «caer» en ningún momento."""
    jugadores = [
        jugador(1, hi_por_min=40.0),
        jugador(2, hi_por_min=42.0),
        jugador(3, hi_por_min=38.0),
        jugador(4, hi_por_min=10.0),      # muy por debajo de la mediana
    ]
    panel = build_dashboard(informe(jugadores), calidad_buena())
    flojo = next(f for f in panel["players"] if f["track_id"] == 4)
    assert flojo["status"] == STATUS_WATCH
    assert flojo["reason"] == "poca_intensidad"


def test_la_mediana_se_calcula_por_equipo_y_no_entre_los_veintidos():
    """Dos equipos pueden jugar a ritmos distintos; mezclarlos señala al equipo lento entero."""
    jugadores = [jugador(i, team="team_1", hi_por_min=60.0) for i in range(1, 4)]
    jugadores += [jugador(i, team="team_2", hi_por_min=20.0) for i in range(4, 7)]
    panel = build_dashboard(informe(jugadores), calidad_buena())
    lentos = [f for f in panel["players"] if f["team"] == "team_2"]
    assert all(f["status"] == STATUS_OK for f in lentos)


def test_la_lista_de_atencion_pone_primero_lo_mas_urgente():
    jugadores = [
        jugador(1, caida=-18.0),
        jugador(2, caida=-40.0),
        jugador(3, caida=-2.0),
    ]
    panel = build_dashboard(informe(jugadores), calidad_buena())
    assert [f["track_id"] for f in panel["attention"]] == [2, 1]
    assert panel["attention"][0]["status"] == STATUS_SUBSTITUTE


def test_un_jugador_sin_referencia_no_se_marca_pero_se_explica():
    panel = build_dashboard(informe([jugador(1, caida=None)]), calidad_buena())
    fila = panel["players"][0]
    assert fila["status"] == STATUS_OK
    assert fila["reason"] == "sin_referencia"


# ── Los umbrales son heurísticos y viajan con el resultado ──────────────
def test_el_panel_declara_con_que_umbrales_decidio():
    """Quien lee un «cambio» tiene derecho a saber con qué corte se decidió."""
    panel = build_dashboard(informe([jugador(1)]), calidad_buena())
    umbrales = panel["thresholds"]
    assert umbrales["dropoff_substitute_pct"] == -25.0
    assert "heurístico" in umbrales["note"].lower()
    assert "no sustituye" in umbrales["note"].lower()


def test_mover_los_umbrales_cambia_el_semaforo():
    """Si no se pudieran ajustar, serían una constante disfrazada de criterio."""
    laxo = DashboardConfig(dropoff_substitute_pct=-50.0, dropoff_watch_pct=-40.0)
    panel = build_dashboard(informe([jugador(1, caida=-35.0)]), calidad_buena(), laxo)
    assert panel["players"][0]["status"] == STATUS_OK


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dropoff_substitute_pct": -10.0, "dropoff_watch_pct": -25.0},   # invertidos
        {"top_n": 0},
        {"low_intensity_ratio": 0.0},
        {"low_intensity_ratio": 1.5},
        {"fragmentation_warn": 2.0, "fragmentation_critical": 1.5},
    ],
)
def test_una_configuracion_incoherente_se_rechaza(kwargs):
    with pytest.raises(ValueError):
        DashboardConfig(**kwargs)


# ── Forma del panel ─────────────────────────────────────────────────────
def test_los_rankings_estan_acotados_a_top_n():
    jugadores = [jugador(i, hi_por_min=float(i)) for i in range(1, 12)]
    panel = build_dashboard(informe(jugadores), calidad_buena(), DashboardConfig(top_n=3))
    for nombre, ranking in panel["leaderboards"].items():
        assert len(ranking) == 3, nombre


def test_los_jugadores_salen_ordenados_por_intensidad():
    jugadores = [jugador(1, hi_por_min=10.0), jugador(2, hi_por_min=50.0)]
    panel = build_dashboard(informe(jugadores), calidad_buena())
    assert [f["track_id"] for f in panel["players"]] == [2, 1]


def test_un_partido_sin_jugadores_no_revienta():
    panel = build_dashboard(informe([]), calidad_buena(players_tracked=0))
    assert panel["players"] == []
    assert panel["attention"] == []
    assert panel["quality"]["fragmentation"] is None


def test_el_panel_funciona_sobre_un_informe_de_verdad():
    """El acoplamiento con `build_report` se rompe en silencio si no se prueba."""
    from fcopilot.kinematics import PlayerKinematics, Sample
    from fcopilot.possession import PossessionTracker
    from fcopilot.report import build_report

    jugadores = {}
    for tid, velocidad in ((1, 18.0), (2, 8.0)):
        kin = PlayerKinematics(tid)
        for i in range(200):
            t = i * 0.2
            kin.update(Sample(frame=i, t=t, x=0.0, y=0.0, wx=t * velocidad / 3.6, wy=0.0))
        kin.finalize()
        jugadores[tid] = {"kinematics": kin, "name": f"J{tid}", "team": "team_1"}

    reporte = build_report(jugadores, PossessionTracker(), calibrated=True,
                           duration_s=40.0, include_positions=False)
    panel = build_dashboard(reporte)

    assert len(panel["players"]) == 2
    assert panel["players"][0]["track_id"] == 1          # el que corre más
    assert panel["players"][0]["hi_m_per_min"] > 0
    assert panel["quality"]["calibrated"] is True


def test_un_partido_vacio_no_dice_que_falto_la_fusion():
    """`fragmentacion` es None con cero jugadores, y eso no es «no se fusionó».

    El aviso miraba el cociente en vez del dato, así que un panel recién abierto
    —sin un solo jugador todavía— acusaba de no haber fusionado nada.
    """
    panel = build_dashboard(
        informe([]), calidad_buena(players_tracked=0, identities_before_merge=0)
    )
    assert "sin_fusion" not in [a["code"] for a in panel["quality"]["warnings"]]


def test_visto_dos_segundos_no_es_correr_a_130_metros_por_minuto():
    """Se vio al ejecutarlo con material real, y encabezaba el ranking.

    Un jugador seguido dos segundos que dio cuatro pasos aparecía con 130 m/min
    de alta intensidad, por delante de quien había jugado el partido entero. El
    núcleo devuelve ahora `None` para esa tasa, y el panel tiene que tratarlo:
    ni cero —que diría que no corrió— ni el primer puesto.
    """
    fugaz = jugador(9, minutos=60.0)
    fugaz["load"]["per_minute"] = {"dist_m": None, "high_intensity_m": None}
    panel = build_dashboard(informe([jugador(1, hi_por_min=40.0), fugaz]), calidad_buena())

    assert [f["track_id"] for f in panel["players"]] == [1, 9]
    assert panel["players"][1]["hi_m_per_min"] is None
    assert [e["track_id"] for e in panel["leaderboards"]["intensity_per_min"]] == [1]


def test_sin_tasa_fiable_no_se_acusa_a_nadie_de_no_correr():
    """`None` no es «por debajo de la mediana»: es «no se sabe»."""
    fugaz = jugador(9, minutos=60.0)
    fugaz["load"]["per_minute"] = {"dist_m": None, "high_intensity_m": None}
    jugadores = [jugador(i, hi_por_min=40.0) for i in range(1, 4)] + [fugaz]
    panel = build_dashboard(informe(jugadores), calidad_buena())

    señalado = next(f for f in panel["players"] if f["track_id"] == 9)
    assert señalado["status"] == STATUS_OK


def test_la_mediana_del_equipo_ignora_a_quien_no_tiene_tasa():
    """Un `None` colado como 0 hundiría la mediana y señalaría a medio equipo."""
    fugaz = jugador(9, minutos=60.0)
    fugaz["load"]["per_minute"] = {"dist_m": None, "high_intensity_m": None}
    jugadores = [jugador(i, hi_por_min=40.0) for i in range(1, 4)] + [fugaz, jugador(5, hi_por_min=30.0)]
    panel = build_dashboard(informe(jugadores), calidad_buena())

    # Con la mediana en 40, el de 30 está por encima del 60 % y no se señala.
    assert next(f for f in panel["players"] if f["track_id"] == 5)["status"] == STATUS_OK
