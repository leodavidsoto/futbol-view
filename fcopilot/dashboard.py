"""El panel del director técnico: pocas cifras, y la confianza que merecen.

Qué problema resuelve
---------------------
El informe completo tiene decenas de campos por jugador. Un director técnico en
la banda no lee eso. Lee tres cosas, en este orden:

1. **¿Me puedo fiar de estos números?**
2. **¿Quién está fundido?**
3. **¿Quién no está corriendo?**

Este módulo produce exactamente eso a partir del informe, y nada más.

Por qué la calidad va primero
-----------------------------
Es la diferencia entre una herramienta y un juguete. Si el tracking partió a
cada jugador en tres, o si no hay calibración y las distancias salen de una
escala inventada, **las cifras siguen siendo bonitas y ya no significan nada**.
Un panel que las enseña igual está mintiendo por omisión.

Por eso el panel empieza por un bloque de calidad con avisos explícitos, y por
eso `confianza` puede valer `baja`. Un DT que ve «fragmentación 2,3 identidades
por jugador» sabe que no debe sustituir a nadie por lo que diga la tabla; sin
ese aviso, lo haría.

Los umbrales del semáforo son heurísticos y están declarados
------------------------------------------------------------
Que una caída del 25 % signifique «cámbialo» **no es ciencia**: es un punto de
corte razonable que hay que ajustar con el equipo, la edad y el momento de la
temporada. Van en :class:`DashboardConfig` para que se puedan mover, y el panel
devuelve los umbrales que usó junto a los resultados, para que nadie los tome
por una constante. Esto no es consejo médico ni sustituye a nadie del cuerpo
técnico: es una ordenación de lo que se midió.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

#: Estados del semáforo, de menos a más urgente. Son dato: quien añada uno
#: obtiene su hueco en el resumen sin tocar ninguna condición.
STATUS_OK = "ok"
STATUS_WATCH = "vigilar"
STATUS_SUBSTITUTE = "cambio"
STATUSES = (STATUS_OK, STATUS_WATCH, STATUS_SUBSTITUTE)

#: Niveles de confianza del panel entero.
CONFIDENCE_HIGH = "alta"
CONFIDENCE_MEDIUM = "media"
CONFIDENCE_LOW = "baja"


@dataclass
class DashboardConfig:
    """Umbrales del panel. **Heurísticos, no científicos.**"""

    #: Caída de intensidad a partir de la cual se propone el cambio.
    dropoff_substitute_pct: float = -25.0
    #: Caída a partir de la cual se recomienda vigilar.
    dropoff_watch_pct: float = -15.0
    #: Minutos mínimos jugados para que la caída signifique algo. Con menos, la
    #: ventana de referencia es demasiado corta y el número es ruido.
    min_minutes_for_dropoff: float = 15.0
    #: Fracción de la mediana del equipo por debajo de la cual un jugador
    #: aparece como «no está corriendo».
    low_intensity_ratio: float = 0.6
    #: Identidades por jugador a partir de las cuales la fragmentación invalida
    #: las métricas por jugador. 1,0 sería perfecto.
    fragmentation_warn: float = 1.4
    fragmentation_critical: float = 2.0
    #: Fracción de frames con balón visto por debajo de la cual la posesión no
    #: se puede sostener.
    ball_seen_warn: float = 0.35
    #: Cuántos jugadores se listan en cada ranking del panel.
    top_n: int = 5

    def __post_init__(self) -> None:
        if self.dropoff_substitute_pct > self.dropoff_watch_pct:
            raise ValueError(
                "dropoff_substitute_pct debe ser más severo (más negativo) que "
                "dropoff_watch_pct"
            )
        if self.top_n < 1:
            raise ValueError("top_n debe ser >= 1")
        if not 0.0 < self.low_intensity_ratio <= 1.0:
            raise ValueError("low_intensity_ratio debe estar en (0, 1]")
        if self.fragmentation_critical < self.fragmentation_warn:
            raise ValueError("fragmentation_critical no puede ser menor que fragmentation_warn")


@dataclass
class Quality:
    """Lo que se sabe sobre si las cifras del panel se sostienen."""

    calibrated: bool = False
    time_source: str = "video"
    players_tracked: int = 0
    identities_before_merge: Optional[int] = None
    rejected_steps: int = 0
    frames_analyzed: int = 0
    frames_with_ball: Optional[int] = None
    pitch_name: Optional[str] = None
    pitch_source: Optional[str] = None

    @property
    def fragmentation(self) -> Optional[float]:
        """Identidades creadas por jugador final. 1,0 es perfecto.

        ``None`` si no se ejecutó la fusión: sin ella no se sabe cuántas
        identidades se crearon de más, y suponer que fue una por jugador sería
        justo el error que este bloque existe para evitar.
        """
        if self.identities_before_merge is None or self.players_tracked <= 0:
            return None
        return self.identities_before_merge / self.players_tracked


def _warnings(quality: Quality, config: DashboardConfig) -> List[Dict[str, str]]:
    """Avisos ordenados de más grave a menos.

    Cada aviso dice **qué cifra deja de valer**, no sólo qué pasó: «no hay
    calibración» no le dice nada a nadie; «las distancias son estimaciones»
    sí.
    """
    avisos: List[Dict[str, str]] = []

    fragmentacion = quality.fragmentation
    if fragmentacion is not None and fragmentacion >= config.fragmentation_critical:
        avisos.append({
            "level": "critico",
            "code": "fragmentacion",
            "message": (
                f"El seguimiento creó {fragmentacion:.1f} identidades por jugador. "
                f"Las métricas por jugador reparten entre varios lo que hizo uno: "
                f"no sustituyas a nadie por esta tabla."
            ),
        })
    elif fragmentacion is not None and fragmentacion >= config.fragmentation_warn:
        avisos.append({
            "level": "aviso",
            "code": "fragmentacion",
            "message": (
                f"{fragmentacion:.1f} identidades por jugador: los totales de equipo "
                f"son fiables, los individuales se quedan cortos."
            ),
        })
    elif quality.identities_before_merge is None:
        # Ojo: `fragmentacion` también es None cuando no hay ningún jugador, y
        # eso no significa que no se fusionara. La condición mira el dato de la
        # fusión, no su cociente.
        avisos.append({
            "level": "aviso",
            "code": "sin_fusion",
            "message": (
                "No se fusionaron los trozos de trayectoria, así que un mismo jugador "
                "puede estar contado como varios."
            ),
        })

    if not quality.calibrated:
        avisos.append({
            "level": "critico",
            "code": "sin_calibrar",
            "message": (
                "Sin calibración del campo. Las distancias y velocidades salen de una "
                "escala fija de píxeles por metro que no corresponde a este campo: "
                "sirven para comparar jugadores entre sí, no como metros reales."
            ),
        })

    if quality.time_source != "video":
        avisos.append({
            "level": "aviso",
            "code": "reloj",
            "message": (
                "Métricas medidas sobre el reloj de la cámara, no sobre tiempo de vídeo. "
                "No son comparables con las de un partido grabado."
            ),
        })

    if quality.frames_with_ball is not None and quality.frames_analyzed > 0:
        visto = quality.frames_with_ball / quality.frames_analyzed
        if visto < config.ball_seen_warn:
            avisos.append({
                "level": "aviso",
                "code": "balon",
                "message": (
                    f"El balón se detectó en el {visto * 100:.0f} % de los frames. "
                    f"La posesión y todo lo que dependa del balón es orientativo."
                ),
            })

    if quality.pitch_source == "escalado":
        avisos.append({
            "level": "aviso",
            "code": "campo_escalado",
            "message": (
                "Las marcas del campo están escaladas desde una plantilla, no medidas. "
                "Las posiciones son aproximadas cerca de las áreas."
            ),
        })

    return avisos


def _confidence(avisos: Sequence[Mapping[str, str]]) -> str:
    if any(a["level"] == "critico" for a in avisos):
        return CONFIDENCE_LOW
    if avisos:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_HIGH


def _player_row(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Fila de la tabla del panel a partir de una entrada del informe."""
    carga: Mapping[str, Any] = entry.get("load") or {}
    por_minuto: Mapping[str, Any] = carga.get("per_minute") or {}
    caida = carga.get("dropoff")
    minutos = float(carga.get("observed_s", 0.0)) / 60.0
    return {
        "track_id": entry.get("track_id"),
        "name": entry.get("name"),
        "team": entry.get("team", "unknown"),
        "minutes": round(minutos, 1),
        "dist_m": float(carga.get("total_dist_m", entry.get("total_dist_m", 0.0))),
        # `None` viaja tal cual: significa que el jugador se vio tan poco que
        # extrapolar a un minuto sería inventar. Convertirlo a 0 diría «no
        # corrió» y convertirlo a la tasa cruda le pondría el primero.
        "dist_m_per_min": _tasa(por_minuto.get("dist_m")),
        "high_intensity_m": float(carga.get("high_intensity_m", 0.0)),
        "hi_m_per_min": _tasa(por_minuto.get("high_intensity_m")),
        "sprints": int(carga.get("sprints", entry.get("sprints", 0))),
        "top_speed_kmh": float(entry.get("max_speed_kmh", 0.0)),
        "accelerations": int(carga.get("accelerations", 0)),
        "decelerations": int(carga.get("decelerations", 0)),
        "dropoff_pct": None if not caida else float(caida.get("change_pct", 0.0)),
        "bands_m": dict(carga.get("bands_m") or {}),
    }


def _tasa(valor: Any) -> Optional[float]:
    """Una tasa por minuto, o ``None`` si el núcleo dijo que no es fiable."""
    return None if valor is None else float(valor)


def _median(valores: Sequence[float]) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    mitad = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[mitad]
    return (ordenados[mitad - 1] + ordenados[mitad]) / 2.0


def _classify(
    fila: Mapping[str, Any], mediana_equipo: float, config: DashboardConfig
) -> Dict[str, Any]:
    """Semáforo de un jugador, con el motivo escrito.

    El motivo importa tanto como el color: «cambio» sin decir por qué obliga a
    quien lo lee a fiarse, y nadie debería fiarse de una heurística sin verla.
    """
    caida = fila.get("dropoff_pct")
    minutos = float(fila.get("minutes", 0.0))
    suficiente = minutos >= config.min_minutes_for_dropoff

    if caida is not None and suficiente and caida <= config.dropoff_substitute_pct:
        return {
            "status": STATUS_SUBSTITUTE,
            "reason": "caida_intensidad",
            "detail": (
                f"Su intensidad cayó un {abs(caida):.0f} % en el último tramo respecto "
                f"de lo que venía haciendo él mismo."
            ),
        }
    if caida is not None and suficiente and caida <= config.dropoff_watch_pct:
        return {
            "status": STATUS_WATCH,
            "reason": "caida_intensidad",
            "detail": f"Intensidad un {abs(caida):.0f} % por debajo de su propio ritmo.",
        }
    if (
        mediana_equipo > 0
        and suficiente
        and fila["hi_m_per_min"] is not None
        and fila["hi_m_per_min"] < mediana_equipo * config.low_intensity_ratio
    ):
        return {
            "status": STATUS_WATCH,
            "reason": "poca_intensidad",
            "detail": (
                f"{fila['hi_m_per_min']:.0f} m/min de alta intensidad frente a "
                f"{mediana_equipo:.0f} de mediana de su equipo."
            ),
        }
    if caida is None and suficiente:
        return {
            "status": STATUS_OK,
            "reason": "sin_referencia",
            "detail": "Aún no hay tramo previo suficiente para comparar su ritmo.",
        }
    return {"status": STATUS_OK, "reason": "normal", "detail": ""}


def build_dashboard(
    report: Mapping[str, Any],
    quality: Optional[Quality] = None,
    config: Optional[DashboardConfig] = None,
) -> Dict[str, Any]:
    """Panel de operación a partir de un informe de :func:`build_report`.

    No calcula ninguna métrica nueva: ordena, clasifica y **dice de qué se
    puede uno fiar**. Todo lo que sale de aquí se puede rastrear hasta una
    cifra del informe.
    """
    config = config or DashboardConfig()
    meta: Mapping[str, Any] = report.get("meta") or {}
    quality = quality or Quality(
        calibrated=bool(meta.get("calibrated", False)),
        time_source=str(meta.get("time_source", "video")),
        players_tracked=int((report.get("totals") or {}).get("players_tracked", 0)),
        rejected_steps=int((report.get("totals") or {}).get("rejected_steps", 0)),
        frames_analyzed=int(meta.get("frames_analyzed", 0)),
    )

    filas = [_player_row(e) for e in report.get("players") or []]

    # La mediana se calcula por equipo: comparar a un jugador con la mediana de
    # los veintidós mezcla dos ritmos de partido distintos.
    medianas: Dict[str, float] = {}
    for equipo in {f["team"] for f in filas}:
        del_equipo = [
            f["hi_m_per_min"] for f in filas
            if f["team"] == equipo and f["hi_m_per_min"] is not None
        ]
        medianas[equipo] = _median(del_equipo)

    for fila in filas:
        fila.update(_classify(fila, medianas.get(fila["team"], 0.0), config))

    avisos = _warnings(quality, config)
    orden_estado = {estado: i for i, estado in enumerate(reversed(STATUSES))}
    atencion = sorted(
        (f for f in filas if f["status"] != STATUS_OK),
        key=lambda f: (orden_estado[f["status"]], f.get("dropoff_pct") or 0.0),
    )

    def top(clave: str) -> List[Dict[str, Any]]:
        """Los mejores por *clave*, excluyendo a quien no tiene ese dato.

        Un jugador sin tasa fiable no puede entrar en un ranking de tasas:
        ponerle un 0 le mandaría al último puesto sin haberlo merecido, y
        ponerle su tasa cruda le pondría el primero sin haberla ganado.
        """
        con_dato = [f for f in filas if f.get(clave) is not None]
        return [
            {"track_id": f["track_id"], "name": f["name"], "team": f["team"],
             "value": round(f[clave], 1)}
            for f in sorted(con_dato, key=lambda f: f[clave], reverse=True)[: config.top_n]
        ]

    duracion_min = float(meta.get("duration_s", 0.0)) / 60.0
    return {
        "generated_at": meta.get("exported_at"),
        "match": {
            "minutes": round(duracion_min, 1),
            "frames_analyzed": quality.frames_analyzed,
            "distance_unit": meta.get("distance_unit"),
            "pitch": quality.pitch_name,
        },
        "quality": {
            "confidence": _confidence(avisos),
            "calibrated": quality.calibrated,
            "time_source": quality.time_source,
            "players_tracked": quality.players_tracked,
            "identities_before_merge": quality.identities_before_merge,
            "fragmentation": (
                None if quality.fragmentation is None else round(quality.fragmentation, 2)
            ),
            "rejected_steps": quality.rejected_steps,
            "warnings": avisos,
        },
        "possession": report.get("possession") or {},
        "teams": report.get("teams") or {},
        "attention": atencion,
        # Los jugadores sin tasa fiable van al final: no es que corrieran poco,
        # es que se les vio poco, y encabezar la tabla con ellos sería engañoso.
        "players": sorted(
            filas,
            key=lambda f: (f["hi_m_per_min"] is not None, f["hi_m_per_min"] or 0.0),
            reverse=True,
        ),
        "leaderboards": {
            "intensity_per_min": top("hi_m_per_min"),
            "distance": top("dist_m"),
            "top_speed": top("top_speed_kmh"),
            "sprints": top("sprints"),
            "accelerations": top("accelerations"),
        },
        # Los umbrales viajan con el resultado a propósito: son heurísticos, y
        # quien lea un «cambio» tiene derecho a saber con qué corte se decidió.
        "thresholds": {
            "dropoff_substitute_pct": config.dropoff_substitute_pct,
            "dropoff_watch_pct": config.dropoff_watch_pct,
            "min_minutes_for_dropoff": config.min_minutes_for_dropoff,
            "low_intensity_ratio": config.low_intensity_ratio,
            "note": (
                "Umbrales heurísticos, no clínicos. Ajústalos a tu equipo. Esto ordena "
                "lo que se midió; no sustituye al criterio del cuerpo técnico."
            ),
        },
    }
