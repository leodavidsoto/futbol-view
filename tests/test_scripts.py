"""Los scripts de operación.

Corren desatendidos y sobre datos que no se pueden recuperar —uno borra ficheros
y el otro decide si un fichero de pesos es de fiar—, así que son justo los que no
conviene dejar sin probar. Ninguno de los dos tiene dependencias externas: se
prueban con ficheros temporales y descargas de mentira.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


def _cargar(nombre: str):
    ruta = RAIZ / "scripts" / f"{nombre}.py"
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


pesos = _cargar("fetch_weights")
purga = _cargar("purge_sessions")


# ── fetch_weights ───────────────────────────────────────────────────────
def _crear(path: Path, contenido: bytes = b"pesos falsos") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contenido)
    return pesos.sha256(path)


def test_un_hash_correcto_pasa(tmp_path):
    digest = _crear(tmp_path / "yolo11x.pt")
    assert pesos.verificar(tmp_path / "yolo11x.pt", digest) == "ok"


def test_un_hash_que_no_coincide_para_el_despliegue(tmp_path):
    """Un .pt es un pickle: cargarlo ejecuta código. Si no es el que esperamos, no se usa."""
    _crear(tmp_path / "yolo11x.pt")
    with pytest.raises(pesos.ProvisionError, match="hash no coincide"):
        pesos.verificar(tmp_path / "yolo11x.pt", "0" * 64)


def test_el_mensaje_de_hash_dice_qué_hacer(tmp_path):
    _crear(tmp_path / "yolo11x.pt")
    with pytest.raises(pesos.ProvisionError) as exc:
        pesos.verificar(tmp_path / "yolo11x.pt", "0" * 64)
    assert "no lo uses" in str(exc.value)


def test_sin_hash_declarado_se_avisa_pero_no_se_bloquea(tmp_path):
    _crear(tmp_path / "yolo11x.pt")
    assert pesos.verificar(tmp_path / "yolo11x.pt", None) == "sin-hash"


def test_los_TODO_del_fichero_de_hashes_no_cuentan_como_hash(tmp_path):
    """Si contaran, compararíamos el hash real contra la cadena 'TODO(config)...'."""
    fichero = tmp_path / "weights.sha256.json"
    fichero.write_text(json.dumps({"yolo11x.pt": "TODO(config): sin verificar", "otro.pt": "abc"}), encoding="utf-8")
    assert pesos.cargar_checksums(fichero) == {"otro.pt": "abc"}


def test_el_fichero_de_hashes_real_es_json_valido():
    assert isinstance(pesos.cargar_checksums(), dict)


def test_un_fichero_de_hashes_roto_se_reporta(tmp_path):
    fichero = tmp_path / "weights.sha256.json"
    fichero.write_text("{no es json", encoding="utf-8")
    with pytest.raises(pesos.ProvisionError, match="no es JSON"):
        pesos.cargar_checksums(fichero)


def test_descarga_lo_que_falta(tmp_path):
    descargados = []

    def descargador(url, destino):
        descargados.append(url)
        destino.write_bytes(b"contenido")

    informe = pesos.provisionar(tmp_path, checksums={}, descargador=descargador)
    assert any("yolo11x.pt" in u for u in descargados)
    assert any("[bajando]" in l for l in informe)


def test_no_vuelve_a_descargar_lo_que_ya_esta(tmp_path):
    _crear(tmp_path / "yolo11x.pt")

    def descargador(url, destino):  # pragma: no cover - no debe llamarse
        raise AssertionError("no debería descargar nada")

    pesos.provisionar(tmp_path, checksums={}, descargador=descargador)


def test_check_only_no_descarga_y_delata_lo_que_falta(tmp_path):
    def descargador(url, destino):  # pragma: no cover
        raise AssertionError("--check-only no debe descargar")

    with pytest.raises(pesos.ProvisionError, match="obligatorios"):
        pesos.provisionar(tmp_path, solo_comprobar=True, checksums={}, descargador=descargador)


def test_un_peso_opcional_ausente_no_bloquea(tmp_path):
    """OSNet es opcional: sin él se degrada a KMeans, no se cae el despliegue."""
    _crear(tmp_path / "yolo11x.pt")
    informe = pesos.provisionar(tmp_path, checksums={}, descargador=lambda *a: None)
    assert any("opcional" in l and "osnet" in l for l in informe)


def test_una_descarga_fallida_no_deja_un_fichero_a_medias(tmp_path):
    class Roto:
        def __enter__(self):
            raise OSError("se cortó la red")

        def __exit__(self, *a):
            return False

    destino = tmp_path / "yolo11x.pt"
    with pytest.raises(pesos.ProvisionError, match="no se pudo descargar"):
        pesos.descargar("https://ejemplo/invalido", destino, abridor=lambda url: Roto())
    assert not destino.exists()
    assert not destino.with_suffix(".pt.parcial").exists()


def test_osnet_no_tiene_url_inventada():
    """Regla 2 de AGENTS.md: si falta una URL, TODO(config), no una que lo parezca."""
    assert pesos.PESOS["osnet_x1_0_imagenet.pth"]["url"] is None


# ── purge_sessions ──────────────────────────────────────────────────────
def _sesion(directorio: Path, nombre: str, edad_dias: float, ahora: float = 1_000_000.0) -> Path:
    directorio.mkdir(parents=True, exist_ok=True)
    path = directorio / nombre
    path.write_bytes(b"estado comprimido de mentira")
    import os

    momento = ahora - edad_dias * purga.SEGUNDOS_POR_DIA
    os.utime(path, (momento, momento))
    return path


def test_borra_lo_caducado_y_respeta_lo_reciente(tmp_path):
    ahora = 1_000_000.0
    vieja = _sesion(tmp_path, "vieja.json.gz", 30, ahora)
    nueva = _sesion(tmp_path, "nueva.json.gz", 1, ahora)
    borrados, _ = purga.purgar(tmp_path, max_edad_dias=7, ahora=ahora)
    assert borrados == 1
    assert not vieja.exists() and nueva.exists()


def test_el_simulacro_no_borra_nada(tmp_path):
    ahora = 1_000_000.0
    vieja = _sesion(tmp_path, "vieja.json.gz", 30, ahora)
    borrados, _ = purga.purgar(tmp_path, max_edad_dias=7, dry_run=True, ahora=ahora)
    assert borrados == 1 and vieja.exists()


def test_solo_toca_ficheros_de_sesion(tmp_path):
    """Este script corre desatendido: un glob ancho en un directorio mal
    configurado borraría cosas que no son suyas."""
    ahora = 1_000_000.0
    _sesion(tmp_path, "vieja.json.gz", 30, ahora)
    ajeno = _sesion(tmp_path, "no-tocar.txt", 30, ahora)
    purga.purgar(tmp_path, max_edad_dias=7, ahora=ahora)
    assert ajeno.exists()


def test_una_retencion_de_cero_dias_es_un_error(tmp_path):
    """Cero borraría todo, incluida la sesión que se está usando ahora mismo."""
    with pytest.raises(ValueError, match="borraría todo"):
        purga.sesiones_caducadas(tmp_path, 0)


def test_una_retencion_negativa_tambien(tmp_path):
    with pytest.raises(ValueError):
        purga.sesiones_caducadas(tmp_path, -1)


def test_un_directorio_que_no_existe_no_es_un_error(tmp_path):
    assert purga.sesiones_caducadas(tmp_path / "no-existe", 7) == []


def test_un_directorio_vacio_no_borra_nada(tmp_path):
    assert purga.purgar(tmp_path, max_edad_dias=7) == (0, 0)


def test_devuelve_los_bytes_liberados(tmp_path):
    ahora = 1_000_000.0
    path = _sesion(tmp_path, "vieja.json.gz", 30, ahora)
    esperado = path.stat().st_size
    _, liberados = purga.purgar(tmp_path, max_edad_dias=7, ahora=ahora)
    assert liberados == esperado


def test_la_cli_sale_con_2_ante_una_retencion_invalida(tmp_path, capsys):
    assert purga.main(["--dir", str(tmp_path), "--max-age-days", "0"]) == 2


def test_la_cli_informa_de_lo_que_hizo(tmp_path, capsys):
    _sesion(tmp_path, "vieja.json.gz", 30)
    assert purga.main(["--dir", str(tmp_path), "--max-age-days", "7", "--quiet"]) == 0
    assert "retención: 7 días" in capsys.readouterr().out


# ── make_demo_video ─────────────────────────────────────────────────────
demo = _cargar("make_demo_video")


def test_la_ventana_de_recorte_no_se_sale_de_la_imagen():
    ancho, alto, total = 1920, 1080, 150
    for i in range(total):
        x, y, w, h = demo.ventana_de_recorte(i, total, ancho, alto)
        assert 0 <= x and x + w <= ancho
        assert 0 <= y and y + h <= alto


def test_el_movimiento_es_suave():
    """Un salto brusco dispararía el rechazo de tramos imposibles, y el vídeo
    mediría eso en vez de la tubería."""
    ancho, alto, total = 1920, 1080, 150
    posiciones = [demo.ventana_de_recorte(i, total, ancho, alto)[:2] for i in range(total)]
    saltos = [
        max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        for a, b in zip(posiciones, posiciones[1:])
    ]
    assert max(saltos) <= 12, f"salto máximo de {max(saltos)} px entre frames"


def test_empieza_y_acaba_en_el_mismo_sitio():
    """La panorámica es de ida y vuelta: sin discontinuidad al final."""
    ancho, alto, total = 1920, 1080, 150
    assert demo.ventana_de_recorte(0, total, ancho, alto) == demo.ventana_de_recorte(total - 1, total, ancho, alto)


def test_sin_imagen_de_origen_lo_dice(tmp_path):
    with pytest.raises(FileNotFoundError):
        demo.localizar_fuente(str(tmp_path / "no-existe.jpg"))


def test_genera_un_mp4_reproducible(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    fuente = tmp_path / "origen.png"
    cv2.imwrite(str(fuente), np.full((720, 1280, 3), 60, dtype=np.uint8))
    salida = tmp_path / "demo.mp4"
    frames = demo.generar(salida, fuente, segundos=0.4, fps=25)

    assert frames == 10 and salida.stat().st_size > 0
    captura = cv2.VideoCapture(str(salida))
    try:
        assert captura.isOpened()
        leidos = 0
        while captura.read()[0]:
            leidos += 1
        assert leidos == frames
    finally:
        captura.release()
