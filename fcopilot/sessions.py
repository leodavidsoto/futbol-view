"""Gestión de sesiones de análisis con persistencia en disco.

Cada ``session_id`` tiene su propio :class:`~fcopilot.analyzer.FootballAnalyzer`.
El estado se guarda comprimido y de forma atómica, de modo que un reinicio del
backend no pierde los nombres, equipos ni métricas de un partido en curso.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fcopilot.analyzer import FootballAnalyzer

logger = logging.getLogger("fcopilot.sessions")

SESSION_ID_MAX_LEN = 64


class SessionIdError(ValueError):
    """``session_id`` con formato no admitido."""


class SessionLimitError(RuntimeError):
    """No hay hueco para otra sesión activa."""


def normalize_session_id(raw: Optional[str]) -> str:
    """Valida el identificador de sesión (alfanumérico, ``-`` y ``_``)."""
    value = (raw or "default").strip()
    if not value or len(value) > SESSION_ID_MAX_LEN:
        raise SessionIdError("session_id invalido")
    if not all(ch.isalnum() or ch in ("-", "_") for ch in value):
        raise SessionIdError("session_id invalido")
    return value


class SessionManager:
    """Diccionario de analizadores con TTL, límite y persistencia."""

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        ttl_seconds: int = 1800,
        max_sessions: int = 12,
        analyzer_factory=FootballAnalyzer,
    ):
        self.state_dir = Path(state_dir or os.getenv("SESSION_STATE_DIR", ".session_state"))
        self.ttl_seconds = int(ttl_seconds)
        self.max_sessions = int(max_sessions)
        self._analyzer_factory = analyzer_factory
        self._lock = threading.RLock()
        self._sessions: Dict[str, FootballAnalyzer] = {}
        self.state_dir.mkdir(parents=True, exist_ok=True)

    # ── Persistencia ───────────────────────────────────────────────────
    def _state_path(self, session_id: str) -> Path:
        return self.state_dir / f"{session_id}.json.gz"

    def save(self, session_id: str, analyzer: FootballAnalyzer) -> bool:
        """Guarda el estado. Un fallo de disco no debe tumbar la petición."""
        path = self._state_path(session_id)
        tmp_path = path.with_suffix(".gz.tmp")
        try:
            with gzip.open(tmp_path, "wt", encoding="utf-8") as fh:
                json.dump(analyzer.serialize_state(), fh, ensure_ascii=True)
            tmp_path.replace(path)
            return True
        except Exception as exc:  # pragma: no cover - depende del sistema de ficheros
            logger.warning("No se pudo guardar la sesion %s: %s", session_id, exc)
            tmp_path.unlink(missing_ok=True)
            return False

    def _restore(self, session_id: str, analyzer: FootballAnalyzer) -> bool:
        path = self._state_path(session_id)
        if not path.exists():
            return False
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                analyzer.load_state(json.load(fh))
            logger.info("Sesion restaurada desde disco: %s", session_id)
            return True
        except Exception as exc:
            logger.warning("No se pudo restaurar la sesion %s: %s", session_id, exc)
            return False

    # ── Ciclo de vida ──────────────────────────────────────────────────
    def _cleanup_expired_locked(self) -> int:
        expired = [sid for sid, analyzer in self._sessions.items() if analyzer.is_idle_expired(self.ttl_seconds)]
        for sid in expired:
            self._sessions.pop(sid, None)
            logger.info("Sesion expirada: %s", sid)
        return len(expired)

    def _evict_lru_locked(self) -> Optional[str]:
        """Descarta de memoria la sesión ociosa más antigua (su estado sigue en disco)."""
        idle = [(a.last_accessed_at, sid) for sid, a in self._sessions.items() if a.active_session is None]
        if not idle:
            return None
        _, victim = min(idle)
        self._sessions.pop(victim, None)
        logger.info("Sesion desalojada por limite de memoria: %s", victim)
        return victim

    def get(self, session_id: str) -> FootballAnalyzer:
        with self._lock:
            self._cleanup_expired_locked()
            analyzer = self._sessions.get(session_id)
            if analyzer is None:
                if len(self._sessions) >= self.max_sessions and self._evict_lru_locked() is None:
                    raise SessionLimitError(
                        f"Limite de sesiones activas alcanzado ({self.max_sessions})"
                    )
                analyzer = self._analyzer_factory()
                self._restore(session_id, analyzer)
                self._sessions[session_id] = analyzer
                logger.info("Sesion creada: %s", session_id)
            analyzer.touch()
            return analyzer

    def peek(self, session_id: str) -> Optional[FootballAnalyzer]:
        """Analizador en memoria, sin crearlo ni restaurarlo."""
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: str, purge_state: bool = True) -> bool:
        with self._lock:
            removed = self._sessions.pop(session_id, None) is not None
        if purge_state:
            path = self._state_path(session_id)
            if path.exists():
                path.unlink()
                removed = True
        return removed

    # ── Lectura ────────────────────────────────────────────────────────
    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._cleanup_expired_locked()
            return sorted(
                (
                    {
                        "session_id": sid,
                        **analyzer.session_status(),
                        "frame_count": analyzer.frame_count,
                        "model": analyzer.model_path,
                    }
                    for sid, analyzer in self._sessions.items()
                ),
                key=lambda item: item["session_id"],
            )

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            cleaned = self._cleanup_expired_locked()
            sessions = {sid: a.session_status() for sid, a in self._sessions.items()}
            return {
                "count": len(self._sessions),
                "busy_count": sum(1 for s in sessions.values() if s["active_session"] is not None),
                "cleaned": cleaned,
                "ttl_seconds": self.ttl_seconds,
                "max_sessions": self.max_sessions,
                "sessions": sessions,
            }

    def shutdown(self) -> None:
        """Persiste todas las sesiones vivas (al apagar el servidor)."""
        with self._lock:
            for sid, analyzer in list(self._sessions.items()):
                self.save(sid, analyzer)
