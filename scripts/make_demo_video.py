#!/usr/bin/env python3
"""Genera un vídeo de prueba para el recorrido de extremo a extremo.

El repositorio no traía ninguno, así que el criterio de cierre de `OPERACION`
—«desde un clon limpio, un comando levanta el sistema y analiza un vídeo»— no se
podía verificar ni a mano ni automáticamente.

**Qué es y qué no es.** Esto no es un partido: es una toma sintética construida
haciendo una panorámica sobre una fotografía real de futbolistas. Las personas
son reales y las detecciones del modelo son reales, así que sirve para
comprobar que la tubería entera funciona —detección, tracking, clasificación de
equipos, cinemática, posesión, streaming NDJSON e informe— con datos que el
modelo reconoce de verdad.

**Lo que NO demuestra:** que las métricas se parezcan a la realidad. El
movimiento es de la cámara, no de los jugadores, así que las distancias y
velocidades que salgan son las de una panorámica. Medir la exactitud del
sistema exige un partido etiquetado a mano (ver `ANALISIS.md` §0.7) y eso es
trabajo de campo.

Uso
---
    python3 scripts/make_demo_video.py --salida demo.mp4
    python3 scripts/make_demo_video.py --salida demo.mp4 --segundos 8 --fps 25
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - sin OpenCV no hay nada que hacer
    print("hace falta opencv-python-headless y numpy", file=sys.stderr)
    raise

#: Fotografía de origen. Viene con `ultralytics`; si no está, se puede pasar otra.
FUENTE_POR_DEFECTO = "ultralytics/assets/zidane.jpg"

TAMANO_SALIDA = (854, 480)


def localizar_fuente(ruta: Optional[str]) -> Path:
    """Encuentra la imagen de origen, buscándola dentro de ultralytics si hace falta."""
    if ruta:
        path = Path(ruta).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"no existe {path}")
        return path
    try:
        import ultralytics

        candidata = Path(ultralytics.__file__).parent / "assets" / "zidane.jpg"
        if candidata.exists():
            return candidata
    except ImportError:
        pass
    raise FileNotFoundError(
        "no encontré una imagen de origen. Pasa una con --fuente, o instala "
        "ultralytics, que trae assets/zidane.jpg"
    )


def ventana_de_recorte(
    frame_idx: int, total: int, ancho: int, alto: int, zoom: float = 0.78
) -> Tuple[int, int, int, int]:
    """Recorte que se desplaza en diagonal y suave (ida y vuelta con un coseno).

    El movimiento es suave a propósito: un salto brusco entre frames dispararía
    el rechazo de tramos imposibles de `PlayerKinematics` y el vídeo mediría eso
    en vez de la tubería.
    """
    w_recorte = int(ancho * zoom)
    h_recorte = int(alto * zoom)
    margen_x = ancho - w_recorte
    margen_y = alto - h_recorte

    # 0 → 1 → 0 a lo largo del vídeo, sin discontinuidades.
    fase = 0.5 - 0.5 * math.cos(2 * math.pi * frame_idx / max(total - 1, 1))
    x = int(margen_x * fase)
    y = int(margen_y * (1.0 - fase))
    return x, y, w_recorte, h_recorte


def generar(salida: Path, fuente: Path, segundos: float, fps: float) -> int:
    imagen = cv2.imread(str(fuente))
    if imagen is None:
        raise ValueError(f"no pude leer la imagen {fuente}")
    alto, ancho = imagen.shape[:2]
    total = max(2, int(segundos * fps))

    escritor = cv2.VideoWriter(
        str(salida), cv2.VideoWriter_fourcc(*"mp4v"), fps, TAMANO_SALIDA
    )
    if not escritor.isOpened():
        raise RuntimeError("OpenCV no pudo abrir el escritor de vídeo (¿falta el códec mp4v?)")

    try:
        for i in range(total):
            x, y, w, h = ventana_de_recorte(i, total, ancho, alto)
            escritor.write(cv2.resize(imagen[y : y + h, x : x + w], TAMANO_SALIDA))
    finally:
        escritor.release()
    return total


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salida", default="demo.mp4", help="fichero mp4 a escribir")
    parser.add_argument("--fuente", help=f"imagen de origen (por defecto: {FUENTE_POR_DEFECTO})")
    parser.add_argument("--segundos", type=float, default=6.0)
    parser.add_argument("--fps", type=float, default=25.0)
    args = parser.parse_args(argv)

    try:
        fuente = localizar_fuente(args.fuente)
        salida = Path(args.salida).expanduser()
        frames = generar(salida, fuente, args.segundos, args.fps)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    tamano_mb = salida.stat().st_size / 1024 / 1024
    print(
        f"{salida} — {frames} frames a {args.fps:g} fps "
        f"({frames / args.fps:.1f} s, {tamano_mb:.1f} MB), origen: {fuente.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
