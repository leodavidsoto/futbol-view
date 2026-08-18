# PLATAFORMA — estado

| | |
|---|---|
| **Estado** | NO_INICIADO |
| **Último agente** | orquestador (intake y corte) |
| **Última actualización** | 2026-08-18T22:45:00Z |
| **Contrato publicado** | no — pendiente `worklog/PLATAFORMA/CONTRATO.md` |
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

## Qué falta

1. Cablear el guardia en CI **sobre el diff de la rama**
   (`--diff origin/main --carril <ID>`), para que un turno que toca ficheros
   ajenos no se pueda mezclar. Requiere que el flujo sepa a qué carril pertenece
   la rama: lo más simple es leerlo del nombre de la rama o de una etiqueta.
2. Suelo de cobertura por módulo, con la excepción documentada de
   `fcopilot/osnet.py` (no se puede cubrir sin `torch` y `torch` no entra en CI).
3. Validar las transiciones de `PLANTILLAS.md` leyéndolas como dato, de forma que
   añadir una fila a esa tabla añada su prueba sola.

## Bloqueos activos

- ninguno.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | `carriles.json` es la fuente y `CARRILES.md` la renderiza | Parsear markdown para decidir permisos es frágil; un JSON no se rompe al reformatear una tabla | sí | Invertirlo y escribir un parser de markdown |
| 2 | El guardia no depende de nada externo | Tiene que correr en un clon recién hecho, antes de instalar | sí | Permitir dependencias si hiciera falta un matcher de globs serio |
| 3 | Un fichero versionado que ningún carril reclama es un fallo, no un aviso | Es como se detecta que alguien añadió trabajo fuera del mapa | sí | Bajarlo a aviso si molesta más de lo que ayuda |
| 4 | `FootballCopilot_v2.jsx` queda congelado en vez de borrado | Borrar es de una puerta (A-05) y no es mía | sí | Responder A-05 |

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
