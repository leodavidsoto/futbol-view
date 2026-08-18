"""Construcción del informe del partido.

El export anterior era un volcado de posiciones sin métricas agregadas. Aquí se
produce un informe con la misma información cruda (opcional) más los totales
que se usan de verdad: distancia, velocidad punta, sprints, zonas de esfuerzo y
posesión, tanto por jugador como por equipo.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Mapping, Optional

from fcopilot.kinematics import SPEED_ZONES, PlayerKinematics
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


def _team_block(entries: Iterable[Dict[str, Any]], team: str) -> Dict[str, Any]:
    members = [e for e in entries if e["team"] == team]
    if not members:
        return {
            "players": 0,
            "total_dist_m": 0.0,
            "avg_dist_m": 0.0,
            "top_speed_kmh": 0.0,
            "sprints": 0,
            "zones_m": {name: 0.0 for name, _, _ in SPEED_ZONES},
        }
    total = sum(e["total_dist_m"] for e in members)
    zones = {name: 0.0 for name, _, _ in SPEED_ZONES}
    for entry in members:
        for name, value in entry["zones_m"].items():
            zones[name] = round(zones.get(name, 0.0) + value, 1)
    return {
        "players": len(members),
        "total_dist_m": round(total, 1),
        "avg_dist_m": round(total / len(members), 1),
        "top_speed_kmh": round(max(e["max_speed_kmh"] for e in members), 1),
        "sprints": sum(e["sprints"] for e in members),
        "zones_m": zones,
    }


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
) -> Dict[str, Any]:
    """Informe completo del partido a partir del estado del analizador."""
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
            "config": dict(config or {}),
        },
        "possession": possession.snapshot(),
        "teams": {team: _team_block(entries, team) for team in TEAMS},
        "totals": {
            "players_tracked": len(entries),
            "total_dist_m": round(sum(e["total_dist_m"] for e in entries), 1),
            "sprints": sum(e["sprints"] for e in entries),
            "top_speed_kmh": round(max((e["max_speed_kmh"] for e in entries), default=0.0), 1),
            "rejected_steps": sum(e["rejected_steps"] for e in entries),
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
        },
        "players": entries,
    }
