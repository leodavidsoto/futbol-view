#!/usr/bin/env python3
"""Guardia del corte de carriles.

Este módulo existe porque un checklist que alguien tilda de memoria no detecta
nada. Todo lo que en `AGENTS.md` es una regla verificable se comprueba aquí, se
corre con un comando y sale con código 1 si encuentra hallazgos. Lo que no se
puede automatizar se imprime como preguntas para el revisor humano, para que
sepa qué le toca a él.

Uso
---
    python3 tools/check_carriles.py                     # comprobaciones estáticas
    python3 tools/check_carriles.py --diff main         # + propiedad de lo cambiado
    python3 tools/check_carriles.py --diff main --carril NUCLEO

Sin dependencias externas a propósito: tiene que poder correrse en un entorno
recién clonado, antes de instalar nada.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
MANIFIESTO = ROOT / "carriles.json"
DOC_CARRILES = ROOT / "CARRILES.md"
DOC_ANALISIS = ROOT / "ANALISIS.md"

#: Preguntas que ninguna comprobación puede responder. Se imprimen siempre.
PREGUNTAS_HUMANAS: Tuple[str, ...] = (
    "¿El contrato publicado describe lo que el código hace de verdad, o lo que "
    "su autor pensaba hacer? Un contrato que miente es peor que uno ausente.",
    "¿Las decisiones marcadas como reversibles en STATE.md lo siguen siendo hoy, "
    "con el código que ya hay encima?",
    "¿Las notas para quien retome dicen algo que no se deduzca leyendo el "
    "diff? Si no, no son notas: son ruido.",
)


class Hallazgo(Exception):
    """Error de uso del propio guardia (no un hallazgo del repositorio)."""


# ── Utilidades ──────────────────────────────────────────────────────────
def _glob_a_regex(patron: str) -> re.Pattern:
    """Convierte un glob de rutas a regex. ``**`` cruza directorios, ``*`` no."""
    salida: List[str] = []
    i = 0
    while i < len(patron):
        ch = patron[i]
        if patron.startswith("**", i):
            salida.append(".*")
            i += 2
        elif ch == "*":
            salida.append("[^/]*")
            i += 1
        elif ch == "?":
            salida.append("[^/]")
            i += 1
        else:
            salida.append(re.escape(ch))
            i += 1
    return re.compile("^" + "".join(salida) + "$")


def _git(*args: str) -> str:
    resultado = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if resultado.returncode != 0:
        raise Hallazgo(f"git {' '.join(args)} falló: {resultado.stderr.strip()}")
    return resultado.stdout


def _ficheros_versionados() -> List[str]:
    return [linea for linea in _git("ls-files").splitlines() if linea]


# ── Manifiesto ──────────────────────────────────────────────────────────
class Manifiesto:
    CLAVES_CARRIL = {"objetivo", "depende_de", "depende_para_cerrar", "requisitos", "rutas"}

    def __init__(self, datos: dict):
        self.datos = datos
        self.carriles: Dict[str, dict] = datos.get("carriles", {})
        self.compartidas: Dict[str, dict] = datos.get("rutas_compartidas", {})
        self.congeladas: Dict[str, str] = datos.get("rutas_congeladas", {})
        self._matchers: Dict[str, List[re.Pattern]] = {
            carril: [_glob_a_regex(r) for r in cfg.get("rutas", [])]
            for carril, cfg in self.carriles.items()
        }

    @classmethod
    def cargar(cls, path: Path = MANIFIESTO) -> "Manifiesto":
        if not path.exists():
            raise Hallazgo(f"no existe {path.relative_to(ROOT)}")
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def duenos(self, ruta: str) -> List[str]:
        """Carriles cuyo mapa de rutas cubre *ruta*."""
        return [c for c, patrones in self._matchers.items() if any(p.match(ruta) for p in patrones)]

    def modo_compartido(self, ruta: str) -> Optional[str]:
        entrada = self.compartidas.get(ruta)
        return entrada.get("modo") if entrada else None


# ── Comprobaciones estáticas ────────────────────────────────────────────
def comprobar_estructura(man: Manifiesto) -> List[str]:
    fallos: List[str] = []
    if not man.carriles:
        fallos.append("carriles.json no declara ningún carril")
    for carril, cfg in man.carriles.items():
        faltan = Manifiesto.CLAVES_CARRIL - set(cfg)
        if faltan:
            fallos.append(f"{carril}: faltan claves {sorted(faltan)}")
        if not cfg.get("rutas"):
            fallos.append(f"{carril}: no tiene rutas propias — sin mapa de propiedad no es un carril")
        for dep in list(cfg.get("depende_de", [])) + list(cfg.get("depende_para_cerrar", [])):
            if dep not in man.carriles:
                fallos.append(f"{carril}: depende de «{dep}», que no existe")
    for ruta, entrada in man.compartidas.items():
        if entrada.get("dueno") not in man.carriles:
            fallos.append(f"ruta compartida {ruta}: dueño «{entrada.get('dueno')}» no es un carril")
        if entrada.get("modo") not in {"propietario", "append"}:
            fallos.append(f"ruta compartida {ruta}: modo «{entrada.get('modo')}» desconocido")
    return fallos


def comprobar_ciclos(man: Manifiesto) -> List[str]:
    """Un ciclo de dependencias significa que el corte está mal, no que haga falta orden."""
    ESTADO_ABIERTO, ESTADO_CERRADO = 1, 2
    estado: Dict[str, int] = {}
    fallos: List[str] = []

    def visitar(carril: str, camino: List[str]) -> None:
        estado[carril] = ESTADO_ABIERTO
        for dep in man.carriles[carril].get("depende_de", []):
            if dep not in man.carriles:
                continue
            if estado.get(dep) == ESTADO_ABIERTO:
                ciclo = " → ".join(camino[camino.index(dep):] + [dep]) if dep in camino else f"{carril} → {dep}"
                fallos.append(f"ciclo de dependencias: {ciclo}")
            elif dep not in estado:
                visitar(dep, camino + [dep])
        estado[carril] = ESTADO_CERRADO

    for carril in man.carriles:
        if carril not in estado:
            visitar(carril, [carril])
    return fallos


def comprobar_propiedad_disjunta(man: Manifiesto) -> List[str]:
    """Cada fichero versionado pertenece a exactamente un carril.

    Es la comprobación que convierte «no toques otro carril» de convención en
    algo verificable. Un fichero sin dueño también es un hallazgo: significa que
    alguien añadió trabajo que el mapa no contempla.
    """
    fallos: List[str] = []
    for ruta in _ficheros_versionados():
        if ruta in man.congeladas:
            continue
        duenos = man.duenos(ruta)
        compartida = man.compartidas.get(ruta)
        if compartida:
            # Una ruta compartida ya declara dueño en su tabla; no es huérfana.
            # Lo que sí es un hallazgo es que el mapa de rutas se lo asigne a
            # otro: entonces la tabla y el mapa dicen cosas distintas.
            declarado = compartida.get("dueno")
            discrepan = [c for c in duenos if c != declarado]
            if discrepan:
                fallos.append(
                    f"{ruta}: la tabla de compartidas la da a {declarado} y el mapa de rutas a {sorted(discrepan)}"
                )
            continue
        if len(duenos) > 1:
            fallos.append(f"{ruta}: reclamado por {sorted(duenos)} — las fronteras se solapan")
        elif not duenos:
            fallos.append(f"{ruta}: ningún carril lo reclama — trabajo sin dueño")
    return fallos


def _ids_carriles_en_doc() -> Set[str]:
    if not DOC_CARRILES.exists():
        return set()
    texto = DOC_CARRILES.read_text(encoding="utf-8")
    return set(re.findall(r"^###\s+([A-Z_]+)\s+·", texto, flags=re.MULTILINE))


def comprobar_doc_coincide(man: Manifiesto) -> List[str]:
    """El documento y el manifiesto tienen que decir lo mismo.

    Añadir un carril exige dos pasos —tocar `carriles.json` y tocar
    `CARRILES.md`—, así que omitir el segundo tiene que fallar en el acto y no
    dejar un carril invisible para las personas o para el guardia.
    """
    if not DOC_CARRILES.exists():
        return [f"no existe {DOC_CARRILES.name}"]
    en_doc = _ids_carriles_en_doc()
    en_json = set(man.carriles)
    fallos = []
    for carril in sorted(en_json - en_doc):
        fallos.append(f"{carril} está en carriles.json pero no tiene sección «### {carril} ·» en CARRILES.md")
    for carril in sorted(en_doc - en_json):
        fallos.append(f"{carril} tiene sección en CARRILES.md pero no está en carriles.json")
    return fallos


def comprobar_worklog(man: Manifiesto) -> List[str]:
    fallos = []
    for carril in sorted(man.carriles):
        state = ROOT / "worklog" / carril / "STATE.md"
        if not state.exists():
            fallos.append(f"falta worklog/{carril}/STATE.md — un carril sin relevo no se puede retomar")
    eventos = ROOT / "worklog" / "EVENTS.jsonl"
    if not eventos.exists():
        fallos.append("falta worklog/EVENTS.jsonl")
    else:
        for numero, linea in enumerate(eventos.read_text(encoding="utf-8").splitlines(), 1):
            if not linea.strip():
                continue
            try:
                json.loads(linea)
            except json.JSONDecodeError as exc:
                fallos.append(f"worklog/EVENTS.jsonl:{numero}: no es JSON válido ({exc.msg})")
    return fallos


def _ids_requisitos_catalogo() -> Set[str]:
    if not DOC_ANALISIS.exists():
        return set()
    texto = DOC_ANALISIS.read_text(encoding="utf-8")
    return set(re.findall(r"^\|\s*(R-\d+)\s*\|", texto, flags=re.MULTILINE))


def comprobar_trazabilidad(man: Manifiesto) -> List[str]:
    """Cada requisito del catálogo tiene exactamente un carril responsable.

    Un requisito huérfano es un agujero en el corte; uno duplicado, una frontera
    mal puesta. Las dos cosas sólo se ven aquí.
    """
    if not DOC_ANALISIS.exists():
        return [f"no existe {DOC_ANALISIS.name} — sin catálogo no hay trazabilidad que comprobar"]
    catalogo = _ids_requisitos_catalogo()
    if not catalogo:
        return ["ANALISIS.md no contiene ninguna fila «| R-xx |» de catálogo"]

    asignados: Dict[str, List[str]] = {}
    for carril, cfg in man.carriles.items():
        for req in cfg.get("requisitos", []):
            asignados.setdefault(req, []).append(carril)

    fallos = []
    for req in sorted(catalogo - set(asignados)):
        fallos.append(f"{req} no lo cubre ningún carril — agujero en el corte")
    for req in sorted(set(asignados) - catalogo):
        fallos.append(f"{req} lo reclama {asignados[req]} pero no está en el catálogo de ANALISIS.md")
    for req, duenos in sorted(asignados.items()):
        if len(duenos) > 1:
            fallos.append(f"{req} lo reclaman {sorted(duenos)} — frontera mal puesta")
    return fallos


# ── Comprobación del diff ───────────────────────────────────────────────
def _ficheros_cambiados(base: str) -> List[str]:
    salida = _git("diff", "--name-only", f"{base}...HEAD")
    return [linea for linea in salida.splitlines() if linea]


def _tiene_borrados(base: str, ruta: str) -> bool:
    diff = _git("diff", f"{base}...HEAD", "--", ruta)
    return any(l.startswith("-") and not l.startswith("---") for l in diff.splitlines())


def comprobar_diff(man: Manifiesto, base: str, carril: Optional[str]) -> List[str]:
    """Lo que este turno tocó, ¿es suyo?"""
    if carril and carril not in man.carriles:
        raise Hallazgo(f"«{carril}» no es un carril declarado")
    fallos = []
    for ruta in _ficheros_cambiados(base):
        if ruta in man.congeladas:
            fallos.append(f"{ruta}: ruta congelada — {man.congeladas[ruta]}")
            continue
        if man.modo_compartido(ruta) == "append":
            if _tiene_borrados(base, ruta):
                fallos.append(f"{ruta}: es de sólo añadir; este diff borra o reescribe líneas previas")
            continue
        duenos = man.duenos(ruta)
        if not duenos:
            fallos.append(f"{ruta}: cambiado sin que ningún carril lo reclame")
        elif carril and carril not in duenos:
            fallos.append(f"{ruta}: pertenece a {sorted(duenos)}, y este turno es de {carril}")
    return fallos


# ── Informe ─────────────────────────────────────────────────────────────
def ejecutar(base: Optional[str], carril: Optional[str]) -> int:
    man = Manifiesto.cargar()

    bloques: List[Tuple[str, List[str]]] = [
        ("estructura del manifiesto", comprobar_estructura(man)),
        ("dependencias sin ciclos", comprobar_ciclos(man)),
        ("propiedad de rutas disjunta", comprobar_propiedad_disjunta(man)),
        ("manifiesto y CARRILES.md coinciden", comprobar_doc_coincide(man)),
        ("worklog completo", comprobar_worklog(man)),
        ("trazabilidad requisito → carril", comprobar_trazabilidad(man)),
    ]
    if base:
        etiqueta = f"propiedad de lo cambiado desde {base}"
        bloques.append((etiqueta + (f" (turno de {carril})" if carril else ""), comprobar_diff(man, base, carril)))

    total = 0
    for titulo, fallos in bloques:
        marca = "FALLA" if fallos else "  ok "
        print(f"[{marca}] {titulo}")
        for fallo in fallos:
            print(f"         · {fallo}")
        total += len(fallos)

    print()
    print("Lo que este guardia no puede comprobar y le toca al revisor:")
    for pregunta in PREGUNTAS_HUMANAS:
        print(f"  · {pregunta}")

    print()
    if total:
        print(f"{total} hallazgo(s).")
        return 1
    print("Sin hallazgos.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Comprueba el corte de carriles de este repositorio.")
    parser.add_argument("--diff", metavar="BASE", help="rama o commit contra el que comparar lo cambiado")
    parser.add_argument("--carril", metavar="ID", help="carril al que pertenece este turno")
    args = parser.parse_args(argv)
    if args.carril and not args.diff:
        parser.error("--carril sólo tiene sentido junto a --diff")
    try:
        return ejecutar(args.diff, args.carril)
    except Hallazgo as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
