"""Construcción del informe del partido.

El export anterior era un volcado de posiciones sin métricas agregadas. Aquí se
produce un informe con la misma información cruda (opcional) más los totales
que se usan de verdad: distancia, velocidad punta, sprints, zonas de esfuerzo y
posesión, tanto por jugador como por equipo.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Mapping, Optional

from fcopilot.kinematics import TIME_SOURCE_VIDEO, PlayerKinematics
from fcopilot.load import SquadLoad
from fcopilot.possession import TEAM_1, TEAM_2, PossessionTracker

TEAMS = (TEAM_1, TEAM_2)


def _player_entry(track_id: int, meta: Mapping[str, Any], include_positions: bool) -> Dict[str, Any]:
    kin: PlayerKinematics = meta["kinematics"]
    entry: Dict[str, Any] = {
        "track_id": track_id,
        "name": meta.get("name", f"#{track_id}"),
        "team": meta.get("team", "unknown"),
        **kin.summary(),
    }
    if include_positions:
        entry["positions"] = [s.as_dict() for s in kin.samples]
    return entry


def _carga(entry: Mapping[str, Any], clave: str) -> float:
    """Lee una métrica de carga de un jugador, con 0 si el jugador no la tiene."""
    return float((entry.get("load") or {}).get(clave, 0.0) or 0.0)


def _tasa(entry: Mapping[str, Any], clave: str) -> Optional[float]:
    """Tasa por minuto de un jugador, o ``None`` si no es fiable."""
    valor = ((entry.get("load") or {}).get("per_minute") or {}).get(clave)
    return None if valor is None else float(valor)


def _ranking(entries: Iterable[Dict[str, Any]], clave) -> List[Dict[str, Any]]:
    """Los diez primeros por *clave*, en el formato común de los rankings."""
    ordenados = sorted(entries, key=clave, reverse=True)[:10]
    return [
        {
            "track_id": e["track_id"],
            "name": e["name"],
            "team": e["team"],
            "value": round(clave(e), 1),
        }
        for e in ordenados
    ]


def _team_block(entries: Iterable[Dict[str, Any]], team: str) -> Dict[str, Any]:
    """Agregado de un equipo.

    La suma de carga la hace :class:`SquadLoad`, no un bucle escrito aquí: si
    fueran dos implementaciones, el total del equipo podría no ser la suma de
    sus jugadores y nadie lo notaría.
    """
    members = [e for e in entries if e["team"] == team]
    escuadra = SquadLoad()
    for entry in members:
        escuadra.add(entry.get("load") or {})
    bloque: Dict[str, Any] = dict(escuadra.as_dict())
    bloque["zones_m"] = bloque["bands_m"]
    bloque["top_speed_kmh"] = round(max((e["max_speed_kmh"] for e in members), default=0.0), 1)
    return bloque


def build_report(
    players: Mapping[int, Mapping[str, Any]],
    possession: PossessionTracker,
    *,
    frames: int = 0,
    duration_s: float = 0.0,
    calibrated: bool = False,
    config: Optional[Mapping[str, Any]] = None,
    include_positions: bool = True,
    version: str = "3.0",
    time_source: str = TIME_SOURCE_VIDEO,
) -> Dict[str, Any]:
    """Informe completo del partido a partir del estado del analizador.

    *time_source* viaja hasta el informe a propósito: unas métricas calculadas
    sobre el reloj de la cámara son legítimas en directo y no son comparables
    con las de un vídeo. Etiquetarlas es lo que evita compararlas sin saberlo.
    """
    entries: List[Dict[str, Any]] = [
        _player_entry(int(tid), meta, include_positions) for tid, meta in sorted(players.items())
    ]
    ranked = sorted(entries, key=lambda e: e["total_dist_m"], reverse=True)

    return {
        "meta": {
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "version": version,
            "frames_analyzed": frames,
            "duration_s": round(duration_s, 2),
            "calibrated": calibrated,
            "distance_unit": "m" if calibrated else "m (estimado por escala px/m)",
            "time_source": time_source,
            "time_base_note": (
                "Métricas sobre tiempo de vídeo." if time_source == TIME_SOURCE_VIDEO
                else "Métricas sobre el reloj de la cámara: sólo comparables con otras capturas en directo."
            ),
            "config": dict(config or {}),
        },
        "possession": possession.snapshot(),
        "teams": {team: _team_block(entries, team) for team in TEAMS},
        "totals": {
            "players_tracked": len(entries),
            "total_dist_m": round(sum(e["total_dist_m"] for e in entries), 1),
            "high_intensity_m": round(sum(_carga(e, "high_intensity_m") for e in entries), 1),
            "sprints": sum(int(_carga(e, "sprints")) for e in entries),
            "accelerations": sum(int(_carga(e, "accelerations")) for e in entries),
            "decelerations": sum(int(_carga(e, "decelerations")) for e in entries),
            "top_speed_kmh": round(max((e["max_speed_kmh"] for e in entries), default=0.0), 1),
            "rejected_steps": sum(e["rejected_steps"] for e in entries),
            "duplicate_samples": sum(e.get("duplicate_samples", 0) for e in entries),
        },
        "leaderboards": {
            "distance": [
                {"track_id": e["track_id"], "name": e["name"], "team": e["team"], "value": e["total_dist_m"]}
                for e in ranked[:10]
            ],
            "top_speed": [
                {"track_id": e["track_id"], "name": e["name"], "team": e["team"], "value": e["max_speed_kmh"]}
                for e in sorted(entries, key=lambda e: e["max_speed_kmh"], reverse=True)[:10]
            ],
            "sprints": [
                {"track_id": e["track_id"], "name": e["name"], "team": e["team"], "value": e["sprints"]}
                for e in sorted(entries, key=lambda e: e["sprints"], reverse=True)[:10]
            ],
            "high_intensity": _ranking(entries, lambda e: _carga(e, "high_intensity_m")),
            # Metros por minuto observado: es el único ranking en el que un
            # suplente que entró diez minutos puede aparecer por delante de un
            # titular, y por eso es el que compara esfuerzo y no permanencia.
            # Sólo entra quien tiene una tasa fiable: el núcleo devuelve `None`
            # para quien se vio demasiado poco como para extrapolar a un minuto.
            "intensity_per_min": _ranking(
                [e for e in entries if _tasa(e, "high_intensity_m") is not None],
                lambda e: _tasa(e, "high_intensity_m") or 0.0,
            ),
            "accelerations": _ranking(
                entries, lambda e: _carga(e, "accelerations") + _carga(e, "decelerations")
            ),
        },
        "players": entries,
    }
