"""El guardia del corte de carriles, dentro de la suite.

`tools/check_carriles.py` sólo sirve si se corre. Un comando que alguien tiene
que acordarse de ejecutar no detecta nada, así que aquí se comprueban dos cosas
distintas:

1. Que **este** repositorio cumple sus propias reglas ahora mismo.
2. Que el guardia sabe detectar cada una de las seis formas de romperlas. Un
   guardia que nunca ha fallado no está probado: está sin usar.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

from fcopilot.load import SPEED_BANDS


def _cargar_guardia():
    """Importa el guardia por ruta: no es un paquete y no debe serlo."""
    ruta = RAIZ / "tools" / "check_carriles.py"
    spec = importlib.util.spec_from_file_location("check_carriles", ruta)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


guardia = _cargar_guardia()


@pytest.fixture
def manifiesto_real() -> dict:
    return json.loads((RAIZ / "carriles.json").read_text(encoding="utf-8"))


def _man(datos: dict):
    return guardia.Manifiesto(datos)


# ── 1. El repositorio cumple sus reglas ─────────────────────────────────
def test_el_repositorio_esta_sano():
    """Si esto falla, el corte y el código dejaron de coincidir."""
    assert guardia.ejecutar(base=None, carril=None) == 0


def test_cada_carril_tiene_worklog_y_requisitos(manifiesto_real):
    for carril, cfg in manifiesto_real["carriles"].items():
        assert (RAIZ / "worklog" / carril / "STATE.md").exists(), carril
        assert cfg["requisitos"], f"{carril} no es responsable de ningún requisito"


def test_la_ruta_critica_sigue_siendo_la_declarada(manifiesto_real):
    """NUCLEO → PERCEPCION → API → CLIENTE. Si cambia, CARRILES.md miente."""
    carriles = manifiesto_real["carriles"]
    assert carriles["PERCEPCION"]["depende_de"] == ["NUCLEO"]
    assert set(carriles["API"]["depende_de"]) == {"NUCLEO", "PERCEPCION"}
    assert carriles["CLIENTE"]["depende_de"] == ["API"]
    assert carriles["PLATAFORMA"]["depende_de"] == [], "PLATAFORMA es infraestructura: no consume a nadie"


# ── 2. El guardia detecta cada forma de romperlas ───────────────────────
def test_detecta_rutas_solapadas(manifiesto_real, monkeypatch):
    datos = copy.deepcopy(manifiesto_real)
    datos["carriles"]["CLIENTE"]["rutas"].append("fcopilot/kinematics.py")
    monkeypatch.setattr(guardia, "_ficheros_versionados", lambda: ["fcopilot/kinematics.py"])
    fallos = guardia.comprobar_propiedad_disjunta(_man(datos))
    assert any("se solapan" in f for f in fallos)


def test_detecta_fichero_sin_dueno(manifiesto_real, monkeypatch):
    monkeypatch.setattr(guardia, "_ficheros_versionados", lambda: ["fcopilot/nuevo_modulo.py"])
    fallos = guardia.comprobar_propiedad_disjunta(_man(manifiesto_real))
    assert any("ningún carril lo reclama" in f for f in fallos)


def test_una_ruta_congelada_no_cuenta_como_huerfana(manifiesto_real, monkeypatch):
    """Congelado significa «de nadie a propósito», no «se me olvidó»."""
    monkeypatch.setattr(guardia, "_ficheros_versionados", lambda: ["FootballCopilot_v2.jsx"])
    assert guardia.comprobar_propiedad_disjunta(_man(manifiesto_real)) == []


def test_detecta_ruta_compartida_con_dos_duenos_declarados(manifiesto_real, monkeypatch):
    """La tabla de compartidas y el mapa de rutas no pueden decir cosas distintas."""
    datos = copy.deepcopy(manifiesto_real)
    datos["rutas_compartidas"]["fcopilot/config.py"]["dueno"] = "NUCLEO"
    monkeypatch.setattr(guardia, "_ficheros_versionados", lambda: ["fcopilot/config.py"])
    fallos = guardia.comprobar_propiedad_disjunta(_man(datos))
    assert any("la da a NUCLEO y el mapa de rutas a ['API']" in f for f in fallos)


def test_una_ruta_compartida_coherente_no_es_huerfana(manifiesto_real, monkeypatch):
    monkeypatch.setattr(guardia, "_ficheros_versionados", lambda: ["worklog/EVENTS.jsonl"])
    assert guardia.comprobar_propiedad_disjunta(_man(manifiesto_real)) == []


def test_detecta_ciclo_de_dependencias(manifiesto_real):
    datos = copy.deepcopy(manifiesto_real)
    datos["carriles"]["NUCLEO"]["depende_de"] = ["API"]
    fallos = guardia.comprobar_ciclos(_man(datos))
    assert any("ciclo de dependencias" in f for f in fallos)


def test_detecta_dependencia_inexistente(manifiesto_real):
    datos = copy.deepcopy(manifiesto_real)
    datos["carriles"]["CLIENTE"]["depende_de"] = ["FANTASMA"]
    fallos = guardia.comprobar_estructura(_man(datos))
    assert any("FANTASMA" in f for f in fallos)


def test_detecta_carril_que_falta_en_el_documento(manifiesto_real, tmp_path, monkeypatch):
    """Añadir un carril son dos pasos; omitir el segundo tiene que romper."""
    doc = tmp_path / "CARRILES.md"
    doc.write_text("### NUCLEO · algo\n", encoding="utf-8")
    monkeypatch.setattr(guardia, "DOC_CARRILES", doc)
    fallos = guardia.comprobar_doc_coincide(_man(manifiesto_real))
    assert any("API está en carriles.json pero no tiene sección" in f for f in fallos)


def test_detecta_carril_del_documento_que_no_existe(manifiesto_real, tmp_path, monkeypatch):
    doc = tmp_path / "CARRILES.md"
    secciones = "".join(f"### {c} · x\n" for c in manifiesto_real["carriles"])
    doc.write_text(secciones + "### INVENTADO · x\n", encoding="utf-8")
    monkeypatch.setattr(guardia, "DOC_CARRILES", doc)
    fallos = guardia.comprobar_doc_coincide(_man(manifiesto_real))
    assert any("INVENTADO" in f for f in fallos)


def test_detecta_state_ausente(manifiesto_real, tmp_path, monkeypatch):
    datos = copy.deepcopy(manifiesto_real)
    datos["carriles"]["RECIEN_CORTADO"] = {
        "objetivo": "x",
        "depende_de": [],
        "depende_para_cerrar": [],
        "requisitos": [],
        "rutas": ["inexistente/**"],
    }
    fallos = guardia.comprobar_worklog(_man(datos))
    assert any("worklog/RECIEN_CORTADO/STATE.md" in f for f in fallos)


def test_detecta_requisito_huerfano(manifiesto_real):
    datos = copy.deepcopy(manifiesto_real)
    datos["carriles"]["NUCLEO"]["requisitos"] = [
        r for r in datos["carriles"]["NUCLEO"]["requisitos"] if r != "R-14"
    ]
    fallos = guardia.comprobar_trazabilidad(_man(datos))
    assert any("R-14 no lo cubre ningún carril" in f for f in fallos)


def test_detecta_requisito_duplicado(manifiesto_real):
    datos = copy.deepcopy(manifiesto_real)
    datos["carriles"]["API"]["requisitos"].append("R-14")
    fallos = guardia.comprobar_trazabilidad(_man(datos))
    assert any("R-14 lo reclaman" in f for f in fallos)


def test_detecta_requisito_que_no_esta_en_el_catalogo(manifiesto_real):
    datos = copy.deepcopy(manifiesto_real)
    datos["carriles"]["API"]["requisitos"].append("R-99")
    fallos = guardia.comprobar_trazabilidad(_man(datos))
    assert any("R-99" in f and "no está en el catálogo" in f for f in fallos)


def test_eventos_son_json_por_linea():
    fallos = guardia.comprobar_worklog(guardia.Manifiesto.cargar())
    assert not any("EVENTS.jsonl" in f for f in fallos)


# ── 3. La comprobación sobre el diff ────────────────────────────────────
def _falso_git(cambiados, diff_por_ruta=None):
    diff_por_ruta = diff_por_ruta or {}

    def _git(*args):
        if args[:2] == ("diff", "--name-only"):
            return "\n".join(cambiados) + "\n"
        if args[0] == "diff":
            return diff_por_ruta.get(args[-1], "+una linea nueva\n")
        return ""

    return _git


def test_diff_acepta_lo_que_es_tuyo(manifiesto_real, monkeypatch):
    monkeypatch.setattr(guardia, "_git", _falso_git(["fcopilot/kinematics.py"]))
    assert guardia.comprobar_diff(_man(manifiesto_real), "main", "NUCLEO") == []


def test_diff_rechaza_lo_ajeno(manifiesto_real, monkeypatch):
    monkeypatch.setattr(guardia, "_git", _falso_git(["football_copilot_v2_backend.py"]))
    fallos = guardia.comprobar_diff(_man(manifiesto_real), "main", "NUCLEO")
    assert any("pertenece a ['API']" in f for f in fallos)


def test_diff_rechaza_tocar_una_ruta_congelada(manifiesto_real, monkeypatch):
    monkeypatch.setattr(guardia, "_git", _falso_git(["FootballCopilot_v2.jsx"]))
    fallos = guardia.comprobar_diff(_man(manifiesto_real), "main", "CLIENTE")
    assert any("congelada" in f for f in fallos)


def test_el_log_de_eventos_es_de_solo_anadir(manifiesto_real, monkeypatch):
    """La regla 4: las correcciones no borran historia."""
    ruta = "worklog/EVENTS.jsonl"
    monkeypatch.setattr(
        guardia,
        "_git",
        _falso_git([ruta], {ruta: "--- a/x\n+++ b/x\n-{\"ts\":\"vieja\"}\n+{\"ts\":\"nueva\"}\n"}),
    )
    fallos = guardia.comprobar_diff(_man(manifiesto_real), "main", "NUCLEO")
    assert any("sólo añadir" in f for f in fallos)


def test_anadir_al_log_desde_cualquier_carril_es_valido(manifiesto_real, monkeypatch):
    ruta = "worklog/EVENTS.jsonl"
    monkeypatch.setattr(guardia, "_git", _falso_git([ruta], {ruta: "+{\"ts\":\"nueva\"}\n"}))
    assert guardia.comprobar_diff(_man(manifiesto_real), "main", "OPERACION") == []


def test_carril_desconocido_es_error_de_uso(manifiesto_real, monkeypatch):
    monkeypatch.setattr(guardia, "_git", _falso_git([]))
    with pytest.raises(guardia.Hallazgo):
        guardia.comprobar_diff(_man(manifiesto_real), "main", "NO_EXISTE")


# ── 4. La máquina de estados se lee del documento, no se reimplementa ────
def test_los_estados_validos_salen_de_plantillas():
    """Añadir una fila a la tabla de PLANTILLAS.md añade su estado solo."""
    assert guardia.estados_validos() == {
        "NO_INICIADO", "EN_CURSO", "LISTO_PARA_REVISION", "HECHO", "BLOQUEADO",
    }


def test_todas_las_transiciones_declaradas_usan_estados_validos():
    validos = guardia.estados_validos()
    for desde, hacia in guardia._transiciones_declaradas():
        assert desde in validos and hacia in validos


def test_nadie_aprueba_su_propio_trabajo():
    """No puede existir una transición EN_CURSO → HECHO: la revisión es cruzada."""
    assert ("EN_CURSO", "HECHO") not in guardia._transiciones_declaradas()


def test_detecta_un_estado_inventado(tmp_path, monkeypatch):
    plantillas = tmp_path / "PLANTILLAS.md"
    plantillas.write_text("| `NO_INICIADO` | `EN_CURSO` | x |\n", encoding="utf-8")
    monkeypatch.setattr(guardia, "DOC_PLANTILLAS", plantillas)
    fallos = guardia.comprobar_estados(guardia.Manifiesto.cargar())
    assert any("no está en la tabla" in f for f in fallos)


def test_sin_tabla_de_estados_es_un_fallo(tmp_path, monkeypatch):
    monkeypatch.setattr(guardia, "DOC_PLANTILLAS", tmp_path / "no-existe.md")
    fallos = guardia.comprobar_estados(guardia.Manifiesto.cargar())
    assert any("ninguna transición" in f for f in fallos)


# ── 5. El suelo de cobertura ────────────────────────────────────────────
def _cargar_cobertura():
    ruta = RAIZ / "tools" / "check_cobertura.py"
    spec = importlib.util.spec_from_file_location("check_cobertura", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


cobertura = _cargar_cobertura()


def _informe(porcentajes: dict, total: float = 99.0):
    return {
        "files": {k: {"summary": {"percent_covered": v}} for k, v in porcentajes.items()},
        "totals": {"percent_covered": total},
    }


def test_cada_modulo_medido_tiene_suelo_declarado():
    """Un módulo nuevo sin suelo pasaría desapercibido hasta que se rompiera."""
    informe = RAIZ / "coverage.json"
    if not informe.exists():
        pytest.skip("hace falta pytest --cov-report=json")
    _, avisos = cobertura.evaluar(json.loads(informe.read_text(encoding="utf-8")))
    sin_suelo = [a for a in avisos if "sin suelo declarado" in a]
    assert not sin_suelo, sin_suelo


def test_detecta_un_modulo_por_debajo_de_su_suelo():
    completo = {m: 100.0 for m in cobertura.MINIMOS}
    completo["fcopilot/kinematics.py"] = 50.0
    fallos, _ = cobertura.evaluar(_informe(completo))
    assert any("kinematics" in f and "< 95%" in f for f in fallos)


def test_detecta_un_modulo_que_dejo_de_medirse():
    """Borrar un fichero de tests entero es exactamente esto."""
    parcial = {m: 100.0 for m in cobertura.MINIMOS if m != "fcopilot/report.py"}
    fallos, _ = cobertura.evaluar(_informe(parcial))
    assert any("report.py" in f and "no aparece" in f for f in fallos)


def test_detecta_que_el_total_baja_del_suelo():
    fallos, _ = cobertura.evaluar(_informe({m: 100.0 for m in cobertura.MINIMOS}, total=10.0))
    assert any("TOTAL" in f for f in fallos)


def test_avisa_cuando_un_suelo_se_quedo_corto():
    """Sin esto, la cobertura se erosiona hasta el mínimo declarado y ahí se queda."""
    holgado = {m: 100.0 for m in cobertura.MINIMOS}
    _, avisos = cobertura.evaluar(_informe(holgado))
    assert any("súbelo" in a for a in avisos)


def test_toda_excepcion_de_cobertura_tiene_su_motivo_escrito():
    """Un número bajo sin motivo es un número que alguien baja cuando le estorba."""
    sin_motivo = [m for m, (minimo, motivo) in cobertura.MINIMOS.items() if minimo < 85 and not motivo]
    assert not sin_motivo, f"suelos bajos sin justificar: {sin_motivo}"


# ── El frontend y el backend no pueden discrepar sobre las bandas ───────
FORMAT_JS = RAIZ / "frontend" / "src" / "lib" / "format.js"


def _bandas_del_frontend():
    """Extrae `SPEED_ZONES` de `format.js` sin ejecutar JavaScript."""
    texto = FORMAT_JS.read_text(encoding="utf-8")
    bloque = re.search(r"export const SPEED_ZONES = \[(.*?)\];", texto, re.S)
    assert bloque, "no encuentro SPEED_ZONES en format.js"
    filas = re.findall(
        r'\{\s*name:\s*"([^"]+)",\s*min:\s*([\d.]+),\s*max:\s*([\d.]+|Infinity)',
        bloque.group(1),
    )
    return [
        (nombre, float(bajo), math.inf if alto == "Infinity" else float(alto))
        for nombre, bajo, alto in filas
    ]


def test_las_bandas_del_cliente_son_las_del_nucleo():
    """Un comentario que pide que coincidan no impide que dejen de coincidir.

    Y dejaron de coincidir: el núcleo pasó a los cortes de la bibliografía de
    GPS (7,2 / 14,4 / 19,8 / 25,2 km/h) y el cliente se quedó en los redondos
    7/14/20/25 con otros nombres. El resultado es de los peores que hay: la app
    pintaba a un jugador «en carrera» mientras el informe lo contaba como
    «trote», con las dos cifras salidas del mismo sistema.

    Esta prueba es la que convierte ese comentario en una regla.
    """
    del_cliente = _bandas_del_frontend()
    del_nucleo = [(nombre, bajo, alto) for nombre, bajo, alto in SPEED_BANDS]
    assert del_cliente == del_nucleo, (
        "las bandas de `frontend/src/lib/format.js` no coinciden con "
        "`fcopilot.load.SPEED_BANDS`. Cambia las dos o ninguna."
    )
