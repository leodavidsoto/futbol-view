#!/usr/bin/env python3
"""Provisiona los pesos del modelo y verifica su integridad.

Hasta ahora `yolo11x.pt` se daba por presente: nada lo descargaba y nada
comprobaba que fuera el fichero correcto. En un clon limpio, el análisis fallaba
con un error de `ultralytics` que no decía que faltara un fichero.

Por qué importa la verificación y no sólo la descarga: **un `.pt` es un pickle
de PyTorch, y cargar uno es ejecutar código**. El backend ya restringe la ruta a
`MODEL_ROOT`, pero eso sólo dice *dónde* está el fichero, no *qué* contiene. El
hash es lo que responde a la segunda pregunta.

Uso
---
    python3 scripts/fetch_weights.py --dest ./weights
    python3 scripts/fetch_weights.py --dest ./weights --check-only
    python3 scripts/fetch_weights.py --dest ./weights --print-hashes

Sin dependencias externas: tiene que poder correr antes de instalar nada.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

#: Fichero con los hashes esperados, junto a este script.
CHECKSUMS = Path(__file__).resolve().parent / "weights.sha256.json"

#: Pesos que el sistema usa. `url` a None significa que no hay una fuente
#: oficial estable que podamos fijar: ver la nota de OSNet más abajo.
PESOS: Dict[str, Dict[str, Optional[str]]] = {
    "yolo11x.pt": {
        "url": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x.pt",
        "para": "detección de jugadores y balón",
        "obligatorio": True,
    },
    "osnet_x1_0_imagenet.pth": {
        # TODO(config): los pesos de OSNet no tienen una URL de descarga estable
        # y pública que podamos fijar aquí. La regla 2 de AGENTS.md prohíbe
        # inventar una que parezca real. Quien despliegue con `team_classifier=osnet`
        # tiene que colocarlos a mano y añadir su hash a weights.sha256.json.
        "url": None,
        "para": "re-identificación de jugadores (clasificador de equipos 'osnet')",
        "obligatorio": False,
    },
}

BLOQUE = 1024 * 1024


class ProvisionError(RuntimeError):
    """Algo impide dejar los pesos en un estado utilizable."""


def sha256(path: Path) -> str:
    """Hash del fichero, leído por bloques: los pesos no caben cómodos en RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for bloque in iter(lambda: fh.read(BLOQUE), b""):
            digest.update(bloque)
    return digest.hexdigest()


def cargar_checksums(path: Path = CHECKSUMS) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProvisionError(f"{path.name} no es JSON válido: {exc.msg}") from exc
    return {k: v for k, v in datos.items() if isinstance(v, str) and not v.startswith("TODO")}


def descargar(url: str, destino: Path, abridor=urllib.request.urlopen) -> None:
    """Descarga a un temporal y renombra: nunca deja un fichero a medias en su sitio."""
    temporal = destino.with_suffix(destino.suffix + ".parcial")
    try:
        with abridor(url) as respuesta, temporal.open("wb") as salida:
            shutil.copyfileobj(respuesta, salida, BLOQUE)
    except (urllib.error.URLError, OSError) as exc:
        temporal.unlink(missing_ok=True)
        raise ProvisionError(f"no se pudo descargar {url}: {exc}") from exc
    temporal.replace(destino)


def verificar(path: Path, esperado: Optional[str]) -> str:
    """Devuelve 'ok', 'sin-hash' o lanza si no coincide."""
    if not esperado:
        return "sin-hash"
    real = sha256(path)
    if real != esperado:
        raise ProvisionError(
            f"{path.name}: el hash no coincide.\n"
            f"  esperado: {esperado}\n"
            f"  real:     {real}\n"
            "Un .pt es un pickle y cargarlo ejecuta código: no lo uses. "
            "Bórralo y vuelve a descargarlo, o corrige weights.sha256.json si "
            "el cambio es intencionado."
        )
    return "ok"


def provisionar(
    destino: Path,
    *,
    solo_comprobar: bool = False,
    checksums: Optional[Dict[str, str]] = None,
    descargador=descargar,
) -> List[str]:
    """Deja los pesos en *destino*. Devuelve las líneas del informe."""
    checksums = cargar_checksums() if checksums is None else checksums
    destino.mkdir(parents=True, exist_ok=True)
    informe: List[str] = []
    faltan_obligatorios: List[str] = []

    for nombre, meta in PESOS.items():
        path = destino / nombre
        if not path.exists():
            if solo_comprobar or not meta["url"]:
                marca = "FALTA" if meta["obligatorio"] else "opcional, ausente"
                informe.append(f"[{marca}] {nombre} — {meta['para']}")
                if meta["obligatorio"]:
                    faltan_obligatorios.append(nombre)
                if not meta["url"] and not solo_comprobar:
                    informe.append(f"         sin URL fijada: colócalo a mano en {destino}")
                continue
            informe.append(f"[bajando] {nombre}")
            descargador(str(meta["url"]), path)

        estado = verificar(path, checksums.get(nombre))
        tamano_mb = path.stat().st_size / 1024 / 1024
        if estado == "sin-hash":
            informe.append(
                f"[SIN VERIFICAR] {nombre} ({tamano_mb:.0f} MB) — "
                f"no hay hash en {CHECKSUMS.name}; añádelo con --print-hashes"
            )
        else:
            informe.append(f"[ok] {nombre} ({tamano_mb:.0f} MB), hash verificado")

    if faltan_obligatorios:
        raise ProvisionError(
            "faltan pesos obligatorios: " + ", ".join(faltan_obligatorios) +
            f"\nEjecuta: python3 {Path(__file__).name} --dest {destino}"
        )
    return informe


def imprimir_hashes(destino: Path) -> int:
    """Calcula los hashes de lo que haya, para rellenar weights.sha256.json."""
    salida = {}
    for nombre in PESOS:
        path = destino / nombre
        if path.exists():
            salida[nombre] = sha256(path)
    print(json.dumps(salida, indent=2, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", default="./weights", help="directorio de los pesos (MODEL_ROOT)")
    parser.add_argument("--check-only", action="store_true", help="no descarga; sólo comprueba")
    parser.add_argument("--print-hashes", action="store_true", help="imprime los hashes de lo que haya")
    args = parser.parse_args(argv)

    destino = Path(args.dest).expanduser().resolve()
    if args.print_hashes:
        return imprimir_hashes(destino)

    try:
        for linea in provisionar(destino, solo_comprobar=args.check_only):
            print(linea)
    except ProvisionError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    print(f"\nPesos listos en {destino}. Arranca con MODEL_ROOT={destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
