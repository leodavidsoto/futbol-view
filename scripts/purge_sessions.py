#!/usr/bin/env python3
"""Borra las sesiones de análisis caducadas del disco.

El backend caduca sesiones en memoria por TTL, pero el estado comprimido de
`SESSION_STATE_DIR` se quedaba en disco para siempre: nombres de jugadores,
equipos, calibración y trayectorias de partidos de hace meses.

**El vídeo subido no se guarda nunca** —se borra al terminar el análisis, y eso
no cambia aquí—; lo que este script borra son los datos derivados.

Sobre la política: la retención por defecto es de 7 días, y es una decisión
provisional. La ambigüedad **A-02** de `ANALISIS.md` —si estos datos se pueden
conservar y cuánto— sigue sin respuesta. Siete días es corto a propósito: si la
respuesta es «más», ampliarlo no cuesta nada; si es «menos», haber guardado de
más ya no se puede deshacer.

Uso
---
    python3 scripts/purge_sessions.py --dir .session_state
    python3 scripts/purge_sessions.py --dir .session_state --max-age-days 30
    python3 scripts/purge_sessions.py --dir .session_state --dry-run
    python3 scripts/purge_sessions.py --dir .session_state --loop 3600
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger("purge_sessions")

#: Sólo se tocan ficheros con esta forma. Un glob más ancho en un directorio mal
#: configurado —apuntando a la raíz del proyecto, por ejemplo— borraría cosas que
#: no son suyas, y este script corre desatendido.
PATRON = "*.json.gz"

SEGUNDOS_POR_DIA = 86_400


def sesiones_caducadas(directorio: Path, max_edad_dias: float, ahora: Optional[float] = None) -> List[Path]:
    """Ficheros de sesión sin tocar desde hace más de *max_edad_dias*."""
    if max_edad_dias <= 0:
        raise ValueError("max-age-days debe ser > 0: un valor de 0 borraría todo, incluida la sesión en curso")
    ahora = time.time() if ahora is None else ahora
    limite = ahora - max_edad_dias * SEGUNDOS_POR_DIA
    if not directorio.is_dir():
        return []
    caducadas = []
    for path in sorted(directorio.glob(PATRON)):
        try:
            if path.stat().st_mtime < limite:
                caducadas.append(path)
        except FileNotFoundError:  # pragma: no cover - carrera con el backend
            continue
    return caducadas


def purgar(
    directorio: Path,
    max_edad_dias: float,
    *,
    dry_run: bool = False,
    ahora: Optional[float] = None,
) -> Tuple[int, int]:
    """Borra lo caducado. Devuelve ``(ficheros, bytes)``."""
    ficheros = sesiones_caducadas(directorio, max_edad_dias, ahora)
    total_bytes = 0
    borrados = 0
    for path in ficheros:
        try:
            tamano = path.stat().st_size
        except FileNotFoundError:  # pragma: no cover
            continue
        if dry_run:
            logger.info("[simulacro] borraría %s (%.1f KB)", path.name, tamano / 1024)
        else:
            try:
                path.unlink()
            except OSError as exc:  # pragma: no cover - permisos o disco
                logger.warning("no se pudo borrar %s: %s", path.name, exc)
                continue
            logger.info("borrado %s (%.1f KB)", path.name, tamano / 1024)
        total_bytes += tamano
        borrados += 1
    return borrados, total_bytes


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=".session_state", help="directorio de estado (SESSION_STATE_DIR)")
    parser.add_argument("--max-age-days", type=float, default=7.0, help="edad máxima; por defecto 7 días")
    parser.add_argument("--dry-run", action="store_true", help="dice qué borraría, sin borrar")
    parser.add_argument("--loop", type=float, metavar="SEGUNDOS", help="repite cada N segundos en vez de salir")
    parser.add_argument("--quiet", action="store_true", help="sólo el resumen")
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    directorio = Path(args.dir).expanduser()

    try:
        while True:
            borrados, total = purgar(directorio, args.max_age_days, dry_run=args.dry_run)
            print(
                f"{'simulacro: ' if args.dry_run else ''}"
                f"{borrados} sesión(es), {total / 1024 / 1024:.2f} MB"
                f" (retención: {args.max_age_days:g} días)"
            )
            if not args.loop:
                return 0
            time.sleep(args.loop)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
