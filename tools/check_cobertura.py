#!/usr/bin/env python3
"""Suelo de cobertura por módulo.

Sin esto, la suite pasa igual si alguien borra un fichero de tests entero: el
número global baja un poco y nadie mira. El suelo por módulo convierte «cubre
menos que antes» en un fallo con nombre y apellidos.

Los mínimos son **una tabla de dominio**: se declaran aquí como dato, con el
motivo de cada excepción escrito al lado. Un número sin motivo se convierte en
un número que alguien baja cuando le estorba.

Uso
---
    pytest --cov=fcopilot --cov=football_copilot_v2_backend --cov-report=json
    python3 tools/check_cobertura.py                 # lee coverage.json

Sin dependencias externas.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
INFORME = ROOT / "coverage.json"

#: módulo → (mínimo %, motivo si es más bajo de lo normal)
MINIMOS: Dict[str, Tuple[int, str]] = {
    "fcopilot/__init__.py": (100, ""),
    "fcopilot/kinematics.py": (95, ""),
    "fcopilot/possession.py": (95, ""),
    "fcopilot/report.py": (95, ""),
    "fcopilot/geometry.py": (90, ""),
    "fcopilot/tracking.py": (95, ""),
    "fcopilot/sessions.py": (95, ""),
    "fcopilot/config.py": (90, ""),
    "fcopilot/analyzer.py": (85, "el bucle de frames tiene ramas que sólo se dan con los trackers reales instalados"),
    "fcopilot/teams.py": (85, "las features de color necesitan OpenCV con imágenes reales"),
    "fcopilot/detection.py": (75, "los caminos de YOLO y SAHI exigen las dependencias pesadas, que CI no instala (regla 7)"),
    "fcopilot/osnet.py": (
        30,
        "las líneas 44-180 son la definición de la red y sólo se ejecutan con torch instalado. "
        "Lo que se prueba es la lógica que la rodea, con embeddings sintéticos",
    ),
    "football_copilot_v2_backend.py": (88, ""),
}

#: Suelo global. Más bajo que la media de los módulos a propósito: sirve para
#: detectar que alguien añadió un módulo nuevo sin cubrir, no para presumir.
MINIMO_TOTAL = 80


def cargar(path: Path = INFORME) -> dict:
    if not path.exists():
        raise SystemExit(
            f"no existe {path.name}. Genéralo con:\n"
            "  pytest --cov=fcopilot --cov=football_copilot_v2_backend --cov-report=json"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _normalizar(nombre: str) -> str:
    return nombre.replace("\\", "/").lstrip("./")


def evaluar(informe: dict) -> Tuple[List[str], List[str]]:
    """Devuelve ``(fallos, avisos)``."""
    ficheros = {_normalizar(k): v for k, v in informe.get("files", {}).items()}
    fallos: List[str] = []
    avisos: List[str] = []

    for modulo, (minimo, motivo) in sorted(MINIMOS.items()):
        datos = ficheros.get(modulo)
        if datos is None:
            fallos.append(f"{modulo}: no aparece en el informe — ¿se borró, o se dejó de medir?")
            continue
        real = datos["summary"]["percent_covered"]
        if real + 1e-9 < minimo:
            linea = f"{modulo}: {real:.0f}% < {minimo}% exigido"
            fallos.append(linea + (f"  ({motivo})" if motivo else ""))
        elif real >= minimo + 10 and minimo < 95:
            # El suelo se quedó corto: subirlo es lo que impide que la cobertura
            # se erosione hasta el mínimo declarado.
            avisos.append(f"{modulo}: {real:.0f}% supera con holgura su suelo de {minimo}%; súbelo")

    for modulo in sorted(set(ficheros) - set(MINIMOS)):
        avisos.append(f"{modulo}: medido pero sin suelo declarado en {Path(__file__).name}")

    total = informe.get("totals", {}).get("percent_covered", 0.0)
    if total + 1e-9 < MINIMO_TOTAL:
        fallos.append(f"TOTAL: {total:.0f}% < {MINIMO_TOTAL}% exigido")
    return fallos, avisos


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--informe", default=str(INFORME), help="ruta de coverage.json")
    args = parser.parse_args(argv)

    fallos, avisos = evaluar(cargar(Path(args.informe)))

    for aviso in avisos:
        print(f"[aviso ] {aviso}")
    for fallo in fallos:
        print(f"[FALLA ] {fallo}")

    if fallos:
        print(f"\n{len(fallos)} módulo(s) por debajo de su suelo.")
        return 1
    print(f"\nTodos los módulos cumplen su suelo de cobertura ({len(MINIMOS)} declarados).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
