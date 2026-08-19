"""Geometría de campo: homografía imagen→mundo en numpy puro.

Se implementa aquí (en vez de delegar en ``cv2.findHomography``) por tres
motivos: el núcleo queda testeable sin OpenCV, el resultado es determinista
para los 4 puntos que envía la interfaz, y podemos rechazar cuadriláteros
degenerados antes de calibrar en vez de propagar una matriz inservible.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

Point = Sequence[float]

#: Área mínima (en px²) de un cuadrilátero de calibración para considerarlo válido.
MIN_QUAD_AREA = 100.0


class CalibrationError(ValueError):
    """Los puntos de calibración no permiten calcular una homografía."""


def _as_points(points: Iterable[Point], name: str, minimo: int = 4) -> np.ndarray:
    arr = np.asarray(list(points), dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise CalibrationError(f"{name}: cada punto debe tener 2 coordenadas")
    if arr.shape[0] < minimo:
        raise CalibrationError(f"{name}: se requieren al menos {minimo} puntos")
    if not np.isfinite(arr).all():
        raise CalibrationError(f"{name}: contiene valores no finitos")
    return arr


def polygon_area(points: Sequence[Point]) -> float:
    """Área absoluta de un polígono simple (fórmula del cordón de zapato)."""
    pts = np.asarray(points, dtype=np.float64)
    if pts.shape[0] < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def _triangle_area(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Área del triángulo abc. Cero exacto significa que los tres están alineados."""
    return float(abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2.0)


def quad_is_degenerate(points: Sequence[Point], min_area: float = MIN_QUAD_AREA) -> bool:
    """``True`` si los cuatro puntos no pueden definir una homografía.

    La condición real es **que no haya tres puntos alineados**, y eso no depende
    del orden en que se den. Esta función usaba el área del polígono, que sí
    depende del orden: cuatro esquinas perfectamente válidas señaladas en
    zigzag —arriba-izquierda, arriba-derecha, abajo-izquierda, abajo-derecha,
    que es un orden completamente natural al hacer clic— forman un polígono
    cruzado cuya área por la fórmula del cordón sale **exactamente cero**, y la
    calibración se rechazaba con un mensaje que hablaba de puntos colineales
    cuando no lo eran.

    Se comprueban por eso los cuatro triángulos que forman los puntos de tres en
    tres. El umbral por triángulo es la mitad del de área porque un
    cuadrilátero se descompone en dos triángulos.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.shape[0] < 4:
        return True
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if np.allclose(pts[i], pts[j]):
                return True
    minimo_triangulo = min_area / 2.0
    for i in range(4):
        for j in range(i + 1, 4):
            for k in range(j + 1, 4):
                if _triangle_area(pts[i], pts[j], pts[k]) < minimo_triangulo:
                    return True
    return False


def _normalize(points: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Normalización de Hartley: centroide en el origen y distancia media √2."""
    centroid = points.mean(axis=0)
    shifted = points - centroid
    mean_dist = float(np.sqrt((shifted ** 2).sum(axis=1)).mean())
    scale = np.sqrt(2.0) / mean_dist if mean_dist > 1e-12 else 1.0
    transform = np.array(
        [
            [scale, 0.0, -scale * centroid[0]],
            [0.0, scale, -scale * centroid[1]],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    return shifted * scale, transform


def find_homography(img_points: Iterable[Point], world_points: Iterable[Point]) -> np.ndarray:
    """Homografía 3×3 que lleva puntos de imagen a coordenadas de campo.

    Usa DLT normalizado + SVD, que para 4 correspondencias es exacto y para más
    resuelve por mínimos cuadrados.
    """
    src = _as_points(img_points, "img_points")
    dst = _as_points(world_points, "world_points")
    if src.shape[0] != dst.shape[0]:
        raise CalibrationError("img_points y world_points deben tener el mismo tamano")
    if quad_is_degenerate(src[:4]):
        raise CalibrationError("los puntos de imagen son degenerados (colineales o repetidos)")

    norm_src, t_src = _normalize(src)
    norm_dst, t_dst = _normalize(dst)

    rows: List[List[float]] = []
    for (x, y), (u, v) in zip(norm_src, norm_dst):
        rows.append([-x, -y, -1.0, 0.0, 0.0, 0.0, u * x, u * y, u])
        rows.append([0.0, 0.0, 0.0, -x, -y, -1.0, v * x, v * y, v])
    _, _, vt = np.linalg.svd(np.asarray(rows, dtype=np.float64))
    h_norm = vt[-1].reshape(3, 3)

    homography = np.linalg.inv(t_dst) @ h_norm @ t_src
    if abs(homography[2, 2]) < 1e-12:
        raise CalibrationError("homografia degenerada")
    homography = homography / homography[2, 2]
    if not np.isfinite(homography).all():
        raise CalibrationError("homografia degenerada")
    return homography


def perspective_transform_point(homography: Optional[np.ndarray], px: float, py: float) -> Optional[Tuple[float, float]]:
    """Aplica la homografía a un punto. Devuelve ``None`` si no hay calibración."""
    if homography is None:
        return None
    vec = np.asarray(homography, dtype=np.float64) @ np.array([px, py, 1.0], dtype=np.float64)
    if abs(vec[2]) < 1e-12:
        return None
    x, y = float(vec[0] / vec[2]), float(vec[1] / vec[2])
    if not (np.isfinite(x) and np.isfinite(y)):
        return None
    return x, y


def euclidean(a: Sequence[float], b: Sequence[float]) -> float:
    """Distancia euclídea entre dos puntos 2D."""
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


# ── Zona de juego ───────────────────────────────────────────────────────
#
# Un polígono que delimita dónde puede haber jugadores. Todo lo que el detector
# encuentre fuera se descarta antes de llegar al tracker, que es donde importa:
# un track nacido de un árbol o de un coche aparcado contamina las métricas del
# partido, y ninguna corrección posterior lo arregla.

#: Mínimo de vértices y área para que un polígono delimite algo.
MIN_ZONA_VERTICES = 3
MIN_ZONA_AREA = 100.0


class PlayAreaError(ValueError):
    """Polígono de zona de juego inservible."""


def validate_play_area(points: Sequence[Point]) -> List[Tuple[float, float]]:
    """Comprueba y normaliza el polígono de la zona de juego."""
    try:
        arr = _as_points(points, "zona de juego", minimo=MIN_ZONA_VERTICES)
    except CalibrationError as exc:
        raise PlayAreaError(str(exc)) from exc
    if len(arr) < MIN_ZONA_VERTICES:
        raise PlayAreaError(f"la zona de juego necesita al menos {MIN_ZONA_VERTICES} vertices")
    area = polygon_area(arr)
    if area < MIN_ZONA_AREA:
        raise PlayAreaError(
            f"la zona de juego es degenerada (area {area:.1f} < {MIN_ZONA_AREA}): "
            "revisa que los vertices no esten alineados ni repetidos"
        )
    return [(float(x), float(y)) for x, y in arr]


def point_in_polygon(point: Sequence[float], polygon: Sequence[Point]) -> bool:
    """¿Está el punto dentro del polígono? (lanzamiento de rayo).

    Los vértices y las aristas cuentan como dentro: un jugador justo sobre la
    línea de banda está en juego, y dejarlo fuera por un píxel sería peor que
    el falso positivo que esto viene a evitar.
    """
    if polygon is None or len(polygon) < MIN_ZONA_VERTICES:
        return True                      # sin zona definida, todo vale
    x, y = float(point[0]), float(point[1])
    dentro = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = float(polygon[i][0]), float(polygon[i][1])
        x2, y2 = float(polygon[(i + 1) % n][0]), float(polygon[(i + 1) % n][1])
        # Sobre la arista: dentro por definición.
        if min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9:
            if abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) < 1e-6:
                return True
        if (y1 > y) != (y2 > y):
            corte = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < corte:
                dentro = not dentro
    return dentro
