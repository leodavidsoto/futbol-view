# PLATAFORMA — estado

| | |
|---|---|
| **Estado** | LISTO_PARA_REVISION |
| **Último agente** | claude (turno 1 de PLATAFORMA) |
| **Última actualización** | 2026-08-19T00:10:00Z |
| **Contrato publicado** | sí — `worklog/PLATAFORMA/CONTRATO.md` v1 |
| **Depende de** | nadie. Es la ola 1 |
| **Requisitos asignados** | R-18, R-23 |

## Qué está hecho

- `carriles.json` como fuente de verdad del corte, con rutas propias, compartidas
  y congeladas.
- `tools/check_carriles.py` con seis comprobaciones estáticas más la de propiedad
  sobre un diff.
- `tests/test_gobernanza.py` mete el guardia en la suite: deja de ser un comando
  que alguien recuerda correr.
- `.github/workflows/gobernanza.yml` lo corre en cada push, en modo estático.

Y en este turno:

1. **Guardia en CI sobre el diff**: `.github/workflows/gobernanza.yml` corre
   `--diff --carril <ID>` cuando la rama declara su carril con el prefijo
   `carril/<ID>/...`.
2. **Suelo de cobertura por módulo**: `tools/check_cobertura.py`, con los
   mínimos como tabla de dominio y el motivo de cada excepción escrito al lado.
   Falla también si un módulo **deja de aparecer** en el informe, que es lo que
   pasa al borrar un fichero de tests entero. Cableado en `ci.yml`.
3. **Estados leídos de `PLANTILLAS.md` como dato**: `comprobar_estados` saca los
   estados válidos de la tabla de transiciones del documento, así que añadir una
   fila añade su comprobación sola. Comprobado por mutación: poner `CASI_HECHO`
   en un `STATE.md` tumba el guardia.
4. **Corregido un defecto del corte** que encontró `OPERACION`: ese carril no
   tenía ninguna ruta de tests asignada, así que no podía escribir una prueba sin
   salirse de su mapa. Añadido `tests/test_scripts.py` a sus rutas.

34 pruebas en `tests/test_gobernanza.py` (antes 23).

## Qué falta

1. **Verificación cruzada** (`revisar-carril`) por un agente que no sea este.
2. El guardia comprueba que el estado declarado sea válido, pero **no que la
   transición lo fuera**: nadie detecta un salto de `EN_CURSO` a `HECHO` salvo
   leyendo el log. Es trabajo del orquestador y estaría mejor automatizado.
3. La comprobación de propiedad sobre el diff sólo se activa con ramas
   `carril/<ID>/...`. Una rama con otro nombre pasa sólo las estáticas.

## Bloqueos activos

- ninguno.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | `carriles.json` es la fuente y `CARRILES.md` la renderiza | Parsear markdown para decidir permisos es frágil; un JSON no se rompe al reformatear una tabla | sí | Invertirlo y escribir un parser de markdown |
| 2 | El guardia no depende de nada externo | Tiene que correr en un clon recién hecho, antes de instalar | sí | Permitir dependencias si hiciera falta un matcher de globs serio |
| 3 | Un fichero versionado que ningún carril reclama es un fallo, no un aviso | Es como se detecta que alguien añadió trabajo fuera del mapa | sí | Bajarlo a aviso si molesta más de lo que ayuda |
| 4 | `FootballCopilot_v2.jsx` queda congelado en vez de borrado | Borrar es de una puerta (A-05) y no es mía | sí | Responder A-05 |
| 5 | Los suelos de cobertura son por módulo, no sólo globales | Un suelo global sube y baja con el tamaño del código: borrar un módulo de tests casi no lo mueve. El suelo por módulo señala al culpable | sí | Volver a `--cov-fail-under` a secas |
| 6 | Un suelo bajo exige motivo escrito, y hay una prueba que lo comprueba | Un número bajo sin motivo es un número que alguien baja cuando le estorba | sí | Quitar la prueba y confiar |
| 7 | La comprobación de propiedad en CI se activa por prefijo de rama | Es la señal más simple que ya existe y no obliga a mantener nada aparte | sí | Leerlo de una etiqueta del PR o de un fichero en la rama |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| — | — | — |

## Notas para quien retome

- El guardia comprueba **ficheros versionados** (`git ls-files`), no el disco. Un
  fichero sin añadir a git es invisible para él; es deliberado, pero explica por
  qué a veces «no detecta» algo que estás viendo.
- La comprobación de que `carriles.json` y `CARRILES.md` coincidan depende del
  formato del encabezado: `### <ID> · <título>`. Si alguien cambia el estilo de
  los títulos, la comprobación deja de encontrar carriles y **falla en el sentido
  seguro** (dice que faltan en el documento). Es el comportamiento que quiero,
  pero el mensaje puede despistar.
- El separador de los títulos es `·` (U+00B7), no un guion.
- **El turno de arranque es la única excepción a la regla 3**, y no se le hizo un
  hueco en el guardia a propósito. El orquestador que montó el andamiaje escribió
  los seis `worklog/<CARRIL>/STATE.md`, así que
  `check_carriles.py --diff main --carril PLATAFORMA` reporta cinco ficheros
  ajenos en ese commit — correctamente. La forma de convivir con eso no es
  añadirle una excepción al guardia, que serviría para colar cualquier cosa
  después: el orquestador no es un carril y sus ramas no llevan el prefijo
  `carril/`, que es lo que activa la comprobación de propiedad en CI. A partir de
  aquí, cada `STATE.md` lo escribe su carril.
- Escribir el guardia encontró un fallo en el manifiesto a los cinco minutos:
  `worklog/EVENTS.jsonl` estaba en la tabla de rutas compartidas pero ningún mapa
  de rutas lo cubría, así que salía como fichero sin dueño. La comprobación
  ahora contrasta las dos tablas entre sí, que es un hallazgo más útil que el
  original.
