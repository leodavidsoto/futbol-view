"""Posesión de balón con histéresis y contabilidad en segundos.

La versión previa contaba *frames* y mezclaba dos denominadores distintos, con
lo que ``team_1 + team_2 + none`` no sumaba 100 y el porcentaje dependía de la
velocidad de procesado. Aquí se acumulan segundos reales y se exponen dos
lecturas complementarias:

* :meth:`PossessionTracker.share` — reparto entre equipos (suma 100), que es lo
  que muestra la barra de posesión.
* :meth:`PossessionTracker.percentages` — reparto sobre el tiempo total,
  incluyendo el balón disputado o sin dueño (suma 100).

Además se aplica histéresis: un equipo necesita mantener el balón varios frames
seguidos para que se le adjudique, evitando el parpadeo cuando dos rivales
están a la misma distancia.

**Robos y pérdidas se cuentan por separado** (decisión del carril NUCLEO). El
contador anterior sumaba uno cada vez que el portador pasaba a ser un equipo,
así que la secuencia ``team_1 → none → team_1`` —un despeje que recupera el
mismo equipo— contaba como dos cambios de posesión cuando el balón nunca cambió
de manos. Ahora:

* ``changes`` cuenta **cambios reales de manos**: el balón pasa a un equipo
  distinto del último que lo tuvo. Pasar por ``none`` por el camino da igual.
* ``interruptions`` cuenta las veces que el balón quedó en disputa o sin dueño.

La transición directa ``team_1 → team_2`` sigue existiendo si el rival encadena
``confirm_frames``: no se obliga a pasar por ``none``, porque en un robo limpio
el balón nunca está sin dueño.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

TEAM_1 = "team_1"
TEAM_2 = "team_2"
NONE = "none"


class PossessionTracker:
    """Acumula posesión por equipo a partir del jugador más cercano al balón."""

    def __init__(self, confirm_frames: int = 3):
        if confirm_frames < 1:
            raise ValueError("confirm_frames debe ser >= 1")
        self.confirm_frames = confirm_frames
        self.seconds: Dict[str, float] = {TEAM_1: 0.0, TEAM_2: 0.0, NONE: 0.0}
        self.holder: str = NONE
        self.changes = 0
        self.interruptions = 0
        self._last_team_holder: str = NONE
        self._candidate: str = NONE
        self._candidate_streak = 0

    # ── Selección del portador ─────────────────────────────────────────
    @staticmethod
    def nearest_holder(
        players: Sequence[dict],
        ball_xy: Optional[Tuple[float, float]],
        threshold: float,
        use_world: bool = False,
    ) -> Tuple[str, float]:
        """Equipo del jugador más cercano al balón y su distancia.

        Devuelve ``("none", inf)`` si no hay balón, no hay jugadores o el más
        cercano está por encima de *threshold*.
        """
        if ball_xy is None or not players:
            return NONE, float("inf")
        best_team, best_dist = NONE, float("inf")
        for player in players:
            point = player.get("world_pos") if use_world else player.get("center")
            if not point:
                continue
            dist = ((point[0] - ball_xy[0]) ** 2 + (point[1] - ball_xy[1]) ** 2) ** 0.5
            if dist < best_dist:
                best_dist, best_team = dist, player.get("team", "unknown")
        if best_dist > threshold or best_team not in (TEAM_1, TEAM_2):
            return NONE, best_dist
        return best_team, best_dist

    # ── Actualización ──────────────────────────────────────────────────
    def update(self, candidate: str, dt: float) -> str:
        """Registra *dt* segundos con *candidate* como posible portador."""
        if candidate not in (TEAM_1, TEAM_2):
            candidate = NONE
        if candidate == self._candidate:
            self._candidate_streak += 1
        else:
            self._candidate = candidate
            self._candidate_streak = 1

        if self._candidate != self.holder and self._candidate_streak >= self.confirm_frames:
            self.holder = self._candidate
            if self.holder == NONE:
                # El balón queda en disputa o sin dueño. No es un cambio de
                # posesión: si lo recupera el mismo equipo, nunca cambió de manos.
                self.interruptions += 1
            else:
                if self._last_team_holder not in (NONE, self.holder):
                    self.changes += 1
                self._last_team_holder = self.holder

        if dt > 0:
            self.seconds[self.holder] = self.seconds.get(self.holder, 0.0) + dt
        return self.holder

    # ── Lectura ────────────────────────────────────────────────────────
    @property
    def total_seconds(self) -> float:
        return sum(self.seconds.values())

    @property
    def contested_seconds(self) -> float:
        return self.seconds[TEAM_1] + self.seconds[TEAM_2]

    def share(self) -> Dict[str, float]:
        """Reparto entre equipos (``team_1 + team_2 == 100`` si hubo posesión)."""
        base = self.contested_seconds
        if base <= 0:
            return {TEAM_1: 0.0, TEAM_2: 0.0}
        t1 = round(self.seconds[TEAM_1] / base * 100, 1)
        return {TEAM_1: t1, TEAM_2: round(100.0 - t1, 1)}

    def percentages(self) -> Dict[str, float]:
        """Reparto sobre el tiempo total, incluyendo balón sin dueño."""
        total = self.total_seconds
        if total <= 0:
            return {TEAM_1: 0.0, TEAM_2: 0.0, NONE: 0.0}
        t1 = round(self.seconds[TEAM_1] / total * 100, 1)
        t2 = round(self.seconds[TEAM_2] / total * 100, 1)
        return {TEAM_1: t1, TEAM_2: t2, NONE: round(max(0.0, 100.0 - t1 - t2), 1)}

    def snapshot(self) -> Dict[str, object]:
        return {
            "holder": self.holder,
            "changes": self.changes,
            "interruptions": self.interruptions,
            "seconds": {k: round(v, 2) for k, v in self.seconds.items()},
            "share": self.share(),
            "percentages": self.percentages(),
        }

    def to_state(self) -> Dict[str, object]:
        return {
            "confirm_frames": self.confirm_frames,
            "seconds": dict(self.seconds),
            "holder": self.holder,
            "changes": self.changes,
            "interruptions": self.interruptions,
            "last_team_holder": self._last_team_holder,
        }

    @classmethod
    def from_state(cls, state: Dict[str, object]) -> "PossessionTracker":
        obj = cls(int(state.get("confirm_frames", 3) or 3))
        seconds = state.get("seconds") or {}
        for key in (TEAM_1, TEAM_2, NONE):
            obj.seconds[key] = float(seconds.get(key, 0.0))
        obj.holder = str(state.get("holder", NONE))
        obj.changes = int(state.get("changes", 0))
        obj.interruptions = int(state.get("interruptions", 0))
        # Las sesiones guardadas antes de separar robos de interrupciones no
        # traen este campo: se reconstruye del portador actual, que es lo
        # correcto salvo que el balón estuviera en disputa justo al guardar.
        obj._last_team_holder = str(state.get("last_team_holder") or (obj.holder if obj.holder != NONE else NONE))
        return obj


def possession_timeline(events: List[Tuple[float, str]]) -> List[Dict[str, object]]:
    """Comprime ``(t, equipo)`` en tramos continuos de posesión."""
    timeline: List[Dict[str, object]] = []
    for t, team in events:
        if timeline and timeline[-1]["team"] == team:
            timeline[-1]["end"] = round(t, 2)
        else:
            timeline.append({"team": team, "start": round(t, 2), "end": round(t, 2)})
    return timeline
