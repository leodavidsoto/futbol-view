# Contrato de PLATAFORMA

**Versión:** 1 · **Publicado:** 2026-08-18

Infraestructura de gobierno: su contrato lo consumen todos los carriles y no
consume el de nadie. Nada de aquí importa dependencias externas — tiene que
correr en un clon recién hecho, antes de instalar nada.

## Qué expone

### `carriles.json` — fuente de verdad del corte

```json
{
  "version": 1,
  "carriles": {
    "<ID>": {
      "objetivo": "una frase",
      "depende_de": ["<ID>"],            // contrato necesario para EMPEZAR
      "depende_para_cerrar": ["<ID>"],   // necesario para declararse HECHO
      "requisitos": ["R-nn"],            // IDs de ANALISIS.md
      "rutas": ["glob"]                  // ** cruza directorios, * no
    }
  },
  "rutas_compartidas": { "<ruta>": { "dueno": "<ID>", "modo": "propietario|append", "nota": "..." } },
  "rutas_congeladas":  { "<ruta>": "por qué está congelada" }
}
```

`CARRILES.md` renderiza esto en prosa. **Los dos tienen que coincidir**: es un
cambio de dos pasos y omitir el segundo falla en el acto.

### `tools/check_carriles.py`

```
python3 tools/check_carriles.py                            # 7 comprobaciones estáticas
python3 tools/check_carriles.py --diff <base>              # + todo lo cambiado tiene dueño
python3 tools/check_carriles.py --diff <base> --carril ID  # + es de ESE carril
```

| Comprobación | Qué caza |
|---|---|
| estructura | claves que faltan, dependencias a carriles inexistentes |
| ciclos | `A → B → A`: el corte está mal, no hace falta ordenarlo |
| propiedad disjunta | dos carriles reclaman un fichero, o **ninguno** lo reclama |
| manifiesto ↔ documento | un carril en uno y no en el otro |
| worklog completo | falta un `STATE.md`, o `EVENTS.jsonl` no es JSON por línea |
| trazabilidad | un requisito sin carril, con dos, o que no está en el catálogo |
| estados | un `STATE.md` que declara un estado fuera de `PLANTILLAS.md` |
| `--diff` | ficheros de otro carril, rutas congeladas, borrados en el log de sólo-añadir |

**Códigos de salida:** `0` sin hallazgos · `1` con hallazgos · `2` error de uso.

### `tools/check_cobertura.py`

```
pytest --cov=fcopilot --cov=football_copilot_v2_backend --cov-report=json
python3 tools/check_cobertura.py
```

Suelo **por módulo**, declarado como tabla en el propio fichero con el motivo de
cada excepción escrito al lado. Falla también si un módulo declarado **deja de
aparecer** en el informe, que es lo que pasa al borrar un fichero de tests
entero. Avisa —sin fallar— de un módulo medido sin suelo declarado y de un
suelo que se quedó corto.

### Formato de `EVENTS.jsonl`

Definido en `AGENTS.md` y en `PLANTILLAS.md`. Una línea JSON por turno,
**añadida**. El guardia rechaza cualquier diff que elimine líneas.

### La tabla de estados

Vive en `PLANTILLAS.md` y se lee de ahí como dato. Añadir una fila añade su
comprobación sola; ningún código reimplementa las transiciones.

## Errores

| Situación | Qué pasa | Qué debe hacer quien llama |
|---|---|---|
| `carriles.json` ausente o mal formado | salida 2 con el motivo | Arreglarlo: sin manifiesto no hay nada que comprobar |
| `--carril` que no existe | salida 2 | Usar un ID del manifiesto |
| `coverage.json` ausente | salida 1 con el comando exacto para generarlo | Correr pytest con `--cov-report=json` |
| Fichero versionado sin dueño | hallazgo, salida 1 | Añadirlo a un carril, o congelarlo si es deliberado |

## Qué NO expone

- **El guardia mira ficheros versionados** (`git ls-files`), no el disco. Un
  fichero sin añadir a git es invisible para él.
- **No valida el contenido de un `CONTRATO.md`**, sólo que exista. Que un
  contrato diga la verdad es trabajo de `revisar-carril`, y así está declarado
  en las preguntas que el informe imprime para el revisor.
- **No comprueba las transiciones entre estados**, sólo que el estado declarado
  sea válido. Verificar que nadie saltó de `EN_CURSO` a `HECHO` exige leer el
  log completo y es trabajo del orquestador.
- **El turno de arranque del andamiaje incumple la regla 3 a propósito** y no se
  le hizo hueco en el guardia: ver las notas de `worklog/PLATAFORMA/STATE.md`.

## Quién depende de esto

Los cinco carriles restantes, como `depende_para_cerrar`: ninguno puede
declararse `HECHO` sin que el guardia salga con 0 sobre su diff.
