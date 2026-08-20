"""Pruebas del comportamiento colectivo.

Lo que se fija aquí son afirmaciones que un entrenador leería como ciertas: que
la amplitud es la amplitud, que la longitud del bloque no la marca el portero, y
que cuando no se sabe algo se dice que no se sabe en vez de dar un cero.
"""

from __future__ import annotations

import math

import pytest

from fcopilot.collective import (
    CORRIDORS,
    MIN_PLAYERS_FOR_LINES,
    MIN_PLAYERS_FOR_SHAPE,
    THIRDS,
    CollectiveError,
    Occupancy,
    ShapeSeries,
    ZoneGrid,
    convex_hull,
    line_summary,
    percentile,
    polygon_area,
    split_lines,
    team_shape,
)
from fcopilot.pitch import PITCH_7, PITCH_11


def bloque(filas):
    """Un equipo colocado en filas: [(x, [y, y, ...]), ...]."""
    return [(x, y) for x, ys in filas for y in ys]


# ── La forma del bloque ─────────────────────────────────────────────────
def test_amplitud_y_longitud_son_lo_que_dicen_ser():
    posiciones = bloque([(20.0, [10.0, 30.0, 50.0]), (40.0, [20.0, 40.0])])
    forma = team_shape(posiciones)
    assert forma is not None
    assert forma.length_m == pytest.approx(20.0)     # a lo largo del campo
    assert forma.width_m == pytest.approx(40.0)      # a lo ancho
    assert forma.centroid[0] == pytest.approx(28.0)


def test_con_tres_jugadores_la_forma_es_desconocida_y_no_cero():
    """Publicar una amplitud de tres jugadores invita a compararla con la de once."""
    assert team_shape([(0.0, 0.0), (10.0, 10.0), (20.0, 0.0)]) is None
    assert team_shape([]) is None


def test_el_portero_no_marca_la_longitud_del_bloque():
    """Está treinta metros por detrás y él solo dobla la cifra.

    No sabemos quién es el portero, así que la defensa es estadística: la
    longitud recortada por percentiles es la que se parece a lo que mira un
    entrenador cuando dice «jugamos largos».
    """
    campo = [(40.0, 20.0), (42.0, 30.0), (44.0, 10.0), (46.0, 25.0),
             (48.0, 15.0), (50.0, 35.0), (52.0, 20.0), (54.0, 30.0)]
    con_portero = team_shape(campo + [(8.0, 20.0)])
    assert con_portero is not None

    assert con_portero.length_m > 40.0                       # el portero manda
    assert con_portero.length_trimmed_m < 20.0               # recortada, no


def test_la_superficie_es_la_de_la_envolvente_y_no_la_del_rectangulo():
    """Un equipo en rombo ocupa la mitad que su caja envolvente."""
    rombo = [(0.0, 10.0), (10.0, 0.0), (20.0, 10.0), (10.0, 20.0)]
    forma = team_shape(rombo)
    assert forma is not None
    assert forma.area_m2 == pytest.approx(200.0)             # rombo
    assert forma.length_m * forma.width_m == pytest.approx(400.0)   # su caja


def test_un_equipo_compacto_tiene_menos_dispersion_que_uno_estirado():
    compacto = team_shape([(50.0, 30.0), (52.0, 34.0), (54.0, 30.0), (52.0, 26.0)])
    estirado = team_shape([(10.0, 5.0), (40.0, 60.0), (90.0, 5.0), (50.0, 62.0)])
    assert compacto is not None and estirado is not None
    assert compacto.spread_m < estirado.spread_m


def test_el_resumen_redondea_pero_no_pierde_las_claves():
    datos = team_shape([(0.0, 0.0), (10.0, 5.0), (20.0, 0.0), (10.0, 10.0)]).as_dict()
    assert set(datos) == {
        "players", "centroid", "length_m", "length_trimmed_m",
        "width_m", "area_m2", "spread_m",
    }


# ── Geometría ───────────────────────────────────────────────────────────
def test_la_envolvente_ignora_los_puntos_de_dentro():
    puntos = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (5.0, 5.0)]
    assert len(convex_hull(puntos)) == 4
    assert polygon_area(convex_hull(puntos)) == pytest.approx(100.0)


def test_la_envolvente_no_revienta_con_puntos_repetidos_o_alineados():
    assert polygon_area(convex_hull([(0.0, 0.0), (0.0, 0.0)])) == 0.0
    assert polygon_area(convex_hull([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)])) == 0.0


@pytest.mark.parametrize(
    "valores,q,esperado",
    [([1.0, 2.0, 3.0], 50.0, 2.0), ([1.0, 2.0, 3.0, 4.0], 50.0, 2.5),
     ([5.0], 90.0, 5.0), ([0.0, 10.0], 10.0, 1.0)],
)
def test_percentil(valores, q, esperado):
    assert percentile(valores, q) == pytest.approx(esperado)


def test_un_percentil_sin_valores_se_rechaza():
    with pytest.raises(CollectiveError):
        percentile([], 50.0)


# ── Líneas ──────────────────────────────────────────────────────────────
def test_tres_lineas_claras_se_separan_bien():
    posiciones = bloque([
        (20.0, [15.0, 25.0, 35.0, 45.0]),      # 4 atrás
        (45.0, [18.0, 30.0, 42.0]),            # 3 en medio
        (70.0, [22.0, 38.0]),                  # 2 arriba
    ])
    resumen = line_summary(posiciones)
    assert resumen is not None
    assert [linea["players"] for linea in resumen["lines"]] == [4, 3, 2]
    assert resumen["gaps_m"] == [pytest.approx(25.0), pytest.approx(25.0)]


def test_las_lineas_salen_ordenadas_de_atras_adelante():
    posiciones = bloque([(70.0, [20.0, 40.0]), (20.0, [20.0, 30.0, 40.0]), (45.0, [30.0])])
    resumen = line_summary(posiciones)
    assert resumen is not None
    alturas = [linea["x_m"] for linea in resumen["lines"]]
    assert alturas == sorted(alturas)


def test_una_linea_que_no_es_una_linea_lo_dice_en_su_dispersion():
    """Agrupar siempre devuelve grupos; la dispersión es lo que los desmiente."""
    ordenado = line_summary(bloque([
        (20.0, [10.0, 30.0, 50.0]), (45.0, [20.0, 40.0]), (70.0, [30.0]),
    ]))
    desordenado = line_summary([
        (18.0, 10.0), (25.0, 30.0), (33.0, 50.0),
        (44.0, 20.0), (52.0, 40.0), (66.0, 30.0),
    ])
    assert ordenado is not None and desordenado is not None
    disp_ordenado = max(l["spread_m"] for l in ordenado["lines"])
    disp_desordenado = max(l["spread_m"] for l in desordenado["lines"])
    assert disp_ordenado < disp_desordenado


def test_con_pocos_jugadores_no_se_inventan_lineas():
    assert split_lines([(0.0, 0.0)] * (MIN_PLAYERS_FOR_LINES - 1)) is None
    assert line_summary([(10.0, 10.0), (20.0, 20.0)]) is None


def test_el_agrupamiento_es_determinista():
    """Con inicio aleatorio, el mismo frame daría formaciones distintas."""
    posiciones = bloque([(20.0, [15.0, 35.0]), (45.0, [20.0, 40.0]), (70.0, [25.0, 45.0])])
    primero = line_summary(posiciones)
    for _ in range(5):
        assert line_summary(posiciones) == primero


def test_pedir_cero_lineas_se_rechaza():
    with pytest.raises(CollectiveError):
        split_lines([(float(i), 0.0) for i in range(10)], lines=0)


# ── Rejilla de zonas ────────────────────────────────────────────────────
def test_la_rejilla_es_de_tres_tercios_por_cinco_carriles():
    rejilla = ZoneGrid(PITCH_11)
    assert len(rejilla.names()) == len(THIRDS) * len(CORRIDORS) == 15


def test_cada_punto_cae_en_el_tercio_y_carril_que_le_toca():
    rejilla = ZoneGrid(PITCH_11)          # 105 × 68
    assert rejilla.zone_of(5.0, 3.0) == "tercio_1|banda_1"
    assert rejilla.zone_of(52.5, 34.0) == "tercio_2|centro"
    assert rejilla.zone_of(100.0, 65.0) == "tercio_3|banda_2"


def test_un_jugador_pisando_la_cal_no_se_pierde():
    """El error de la homografía saca de banda al extremo que juega pegado a ella."""
    rejilla = ZoneGrid(PITCH_7)
    assert rejilla.zone_of(-1.5, -0.5) == "tercio_1|banda_1"
    assert rejilla.zone_of(1000.0, 1000.0) == "tercio_3|banda_2"


def test_una_rejilla_sin_divisiones_se_rechaza():
    with pytest.raises(CollectiveError):
        ZoneGrid(PITCH_11, thirds=0)


# ── Ocupación ───────────────────────────────────────────────────────────
def test_la_ocupacion_acumula_segundos_y_reparte_en_porcentaje():
    ocupacion = Occupancy(ZoneGrid(PITCH_11))
    ocupacion.add(5.0, 3.0, 30.0)
    ocupacion.add(52.5, 34.0, 10.0)
    datos = ocupacion.as_dict()
    assert datos["total_s"] == pytest.approx(40.0)
    assert datos["zones"]["tercio_1|banda_1"]["pct"] == pytest.approx(75.0)


def test_la_ocupacion_emite_todas_las_zonas_aunque_esten_vacias():
    """Un hueco en la rejilla es información, y una rejilla incompleta se dibuja mal."""
    ocupacion = Occupancy(ZoneGrid(PITCH_11))
    ocupacion.add(52.5, 34.0, 5.0)
    zonas = ocupacion.as_dict()["zones"]
    assert len(zonas) == 15
    assert zonas["tercio_1|banda_1"]["seconds"] == 0.0


def test_un_tramo_de_duracion_cero_no_ocupa_nada():
    ocupacion = Occupancy(ZoneGrid(PITCH_11))
    ocupacion.add(10.0, 10.0, 0.0)
    assert ocupacion.total_s == 0.0


# ── La serie del partido ────────────────────────────────────────────────
def _alimentar(serie, segundos, posiciones, equipo="team_1", dt=1.0, t0=0.0):
    for i in range(segundos):
        serie.add(t0 + i * dt, dt, {equipo: posiciones})


def test_la_serie_da_media_minimo_y_maximo_sin_guardar_cada_frame():
    serie = ShapeSeries(ZoneGrid(PITCH_7))
    ancho = bloque([(20.0, [5.0, 35.0]), (40.0, [10.0, 30.0])])
    estrecho = bloque([(20.0, [15.0, 25.0]), (40.0, [18.0, 22.0])])
    _alimentar(serie, 30, ancho)
    _alimentar(serie, 30, estrecho, t0=30.0)

    resumen = serie.summary()["teams"]["team_1"]["shape"]["width_m"]
    assert resumen["max"] == pytest.approx(30.0)
    assert resumen["min"] == pytest.approx(10.0)
    assert resumen["samples"] == 60


def test_la_linea_de_tiempo_va_por_bloques_y_sin_huecos():
    serie = ShapeSeries(ZoneGrid(PITCH_7), bucket_s=60.0)
    posiciones = bloque([(20.0, [10.0, 30.0]), (40.0, [15.0, 25.0])])
    _alimentar(serie, 10, posiciones, t0=0.0)
    _alimentar(serie, 10, posiciones, t0=180.0)      # se salta dos bloques

    linea = serie.timeline_for("team_1")
    assert [fila["from_s"] for fila in linea] == [0.0, 60.0, 120.0, 180.0]
    assert linea[1]["samples"] == 0


def test_un_equipo_con_pocos_jugadores_no_entra_en_la_forma_pero_si_ocupa():
    """Se le ve, así que ocupó espacio; pero su «amplitud» no significa nada."""
    serie = ShapeSeries(ZoneGrid(PITCH_7))
    serie.add(0.0, 1.0, {"team_1": [(20.0, 10.0), (25.0, 15.0)]})

    equipo = serie.summary()["teams"]["team_1"]
    assert equipo["shape"] == {}
    assert equipo["occupancy"]["total_s"] == pytest.approx(2.0)


def test_los_dos_equipos_se_miden_por_separado():
    serie = ShapeSeries(ZoneGrid(PITCH_7))
    ancho = bloque([(20.0, [2.0, 38.0]), (30.0, [5.0, 35.0])])
    estrecho = bloque([(50.0, [18.0, 22.0]), (55.0, [19.0, 21.0])])
    serie.add(0.0, 1.0, {"team_1": ancho, "team_2": estrecho})

    equipos = serie.summary()["teams"]
    assert equipos["team_1"]["shape"]["width_m"]["avg"] > equipos["team_2"]["shape"]["width_m"]["avg"]


def test_la_serie_esta_acotada_en_memoria():
    serie = ShapeSeries(ZoneGrid(PITCH_7), bucket_s=1.0)
    posiciones = bloque([(20.0, [10.0, 30.0]), (40.0, [15.0, 25.0])])
    for i in range(ShapeSeries.MAX_BUCKETS + 100):
        serie.add(float(i), 1.0, {"team_1": posiciones})
    assert len(serie.timeline["team_1"]) <= ShapeSeries.MAX_BUCKETS


def test_una_serie_sin_datos_no_revienta():
    serie = ShapeSeries()
    resumen = serie.summary()
    assert resumen["teams"] == {}
    assert resumen["frames"] == 0
    assert serie.timeline_for("team_1") == []


def test_un_bloque_de_duracion_cero_se_rechaza():
    with pytest.raises(CollectiveError):
        ShapeSeries(bucket_s=0)


def test_sin_rejilla_hay_forma_pero_no_ocupacion():
    """La ocupación necesita saber en qué campo se juega; la forma no."""
    serie = ShapeSeries(grid=None)
    serie.add(0.0, 1.0, {"team_1": bloque([(20.0, [10.0, 30.0]), (40.0, [15.0, 25.0])])})
    equipo = serie.summary()["teams"]["team_1"]
    assert equipo["shape"]["width_m"] is not None
    assert equipo["occupancy"] is None


def test_el_minimo_de_jugadores_es_coherente_entre_forma_y_lineas():
    """Partir en tres líneas exige más gente que medir una amplitud."""
    assert MIN_PLAYERS_FOR_LINES >= MIN_PLAYERS_FOR_SHAPE
    assert MIN_PLAYERS_FOR_SHAPE >= 3


def test_la_longitud_recortada_nunca_es_mayor_que_la_completa():
    """Es un recorte: si saliera mayor, el percentil estaría mal."""
    import random

    aleatorio = random.Random(11)
    for _ in range(50):
        puntos = [(aleatorio.uniform(0, 105), aleatorio.uniform(0, 68)) for _ in range(11)]
        forma = team_shape(puntos)
        assert forma is not None
        assert forma.length_trimmed_m <= forma.length_m + 1e-9
        assert forma.area_m2 <= forma.length_m * forma.width_m + 1e-6
        assert math.isfinite(forma.spread_m)


def test_un_tres_dos_uno_perfecto_no_se_lee_como_tres_cero_tres():
    """El k-medias dejaba la línea del medio vacía, y nadie lo habría notado.

    Con inicio por cuantiles, tres jugadores a 20 m, dos a 45 y uno a 70
    convergían a 3-0-3: los de 45 acababan agrupados con el de 70 y el medio
    quedaba vacío. Un entrenador habría leído una formación que no existía.

    En una dimensión las agrupaciones óptimas son intervalos contiguos, así que
    se resuelven exactas probando todos los cortes; ninguno deja grupos vacíos
    por construcción.
    """
    posiciones = [(20.0, 10.0), (20.0, 30.0), (20.0, 50.0),
                  (45.0, 20.0), (45.0, 40.0), (70.0, 30.0)]
    grupos = split_lines(posiciones)
    assert grupos is not None
    assert [len(g) for g in grupos] == [3, 2, 1]
    assert all(g for g in grupos), "ninguna línea puede quedar vacía"


def test_ninguna_linea_queda_vacia_nunca():
    """La propiedad general, no un caso concreto."""
    import random

    aleatorio = random.Random(3)
    for _ in range(60):
        n = aleatorio.randint(MIN_PLAYERS_FOR_LINES, 22)
        posiciones = [(aleatorio.uniform(0, 105), aleatorio.uniform(0, 68)) for _ in range(n)]
        grupos = split_lines(posiciones)
        assert grupos is not None
        assert all(len(g) >= 1 for g in grupos)
        assert sum(len(g) for g in grupos) == n


# ── Persistencia ────────────────────────────────────────────────────────
def test_lo_colectivo_sobrevive_a_un_reinicio():
    """Si no, una sesión restaurada conserva la carga física y pierde el bloque.

    El panel enseñaría media pestaña y nadie sabría por qué.
    """
    serie = ShapeSeries(ZoneGrid(PITCH_7))
    posiciones = bloque([(20.0, [5.0, 35.0]), (30.0, [10.0, 30.0]), (25.0, [20.0]), (35.0, [18.0])])
    _alimentar(serie, 20, posiciones)

    restaurada = ShapeSeries.from_state(serie.to_state(), ZoneGrid(PITCH_7))

    assert restaurada.summary() == serie.summary()
    assert restaurada.frames == serie.frames


def test_restaurar_sin_rejilla_conserva_la_forma_aunque_pierda_la_ocupacion():
    """La ocupación necesita saber en qué campo se juega; la forma no."""
    serie = ShapeSeries(ZoneGrid(PITCH_7))
    _alimentar(serie, 5, bloque([(20.0, [5.0, 35.0]), (30.0, [10.0, 30.0])]))

    restaurada = ShapeSeries.from_state(serie.to_state(), grid=None)

    assert restaurada.summary()["teams"]["team_1"]["shape"]["width_m"] is not None
    assert restaurada.summary()["teams"]["team_1"]["occupancy"] is None


def test_un_estado_vacio_no_revienta():
    restaurada = ShapeSeries.from_state({})
    assert restaurada.frames == 0
    assert restaurada.summary()["teams"] == {}
