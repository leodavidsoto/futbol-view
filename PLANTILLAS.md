# PLANTILLAS.md

Formatos exactos. Cópialos tal cual; las secciones no son opcionales.

---

## `worklog/<CARRIL>/STATE.md`

```markdown
# <CARRIL> — estado

| | |
|---|---|
| **Estado** | NO_INICIADO \| EN_CURSO \| LISTO_PARA_REVISION \| HECHO \| BLOQUEADO |
| **Último agente** | <quién> |
| **Última actualización** | <ISO-8601 UTC> |
| **Contrato publicado** | sí \| no — `worklog/<CARRIL>/CONTRATO.md` |
| **Depende de** | <carriles, con si su contrato está publicado o no> |
| **Requisitos asignados** | <IDs de ANALISIS.md> |

## Qué está hecho

- <hecho verificable, con el fichero o la prueba que lo demuestra>

## Qué falta

- <lo siguiente que haría quien retome, en orden>

## Bloqueos activos

- <ninguno> | <qué bloquea, desde cuándo, y a quién hay que preguntar>

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | | | sí / no / cara | |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|

## Notas para quien retome

- <lo que no se deduce leyendo el diff: trampas, supuestos, cosas que probé y
  no funcionaron y por qué>
```

**Las dos últimas secciones son las que sirven de verdad.** La tabla de
decisiones evita que el siguiente revierta algo por no saber por qué está así —
la columna «reversible» es la que le dice si puede tocarlo sin preguntar. Las
notas son para lo que el código no cuenta: que probaste ByteTrack y descartaba
tracks al cruzarse, que el vídeo de prueba tiene el campo cortado por la
izquierda, que ese `round()` está ahí porque el frontend compara flotantes.

Una nota que repite lo que se ve en el diff es ruido. Bórrala.

---

## `worklog/<CARRIL>/CONTRATO.md`

```markdown
# Contrato de <CARRIL>

**Versión:** <n> · **Publicado:** <fecha> · **Estable desde:** <fecha>

## Qué expone

### <nombre del símbolo, ruta o evento>

<Firma o esquema concreto. No «devuelve las métricas del jugador», sino el
diccionario con sus claves, sus tipos y sus unidades.>

```
<esquema real: firma de función, JSON de ejemplo, tabla de campos con tipo y unidad>
```

<Qué garantiza: invariantes, orden, idempotencia, qué pasa con la entrada vacía.>

## Errores

| Situación | Qué devuelve | Qué debe hacer quien llama |
|---|---|---|
| | | |

## Qué NO expone

- <lo que es interno y no puede asumirse: estructuras mutables que devuelvo por
  referencia, orden que no garantizo, campos que puedo quitar>

## Quién depende de esto

- <carriles, y qué parte usa cada uno>

## Cambios desde la versión anterior

- <qué cambió y si rompe a alguien>
```

**Un contrato que miente es peor que uno ausente.** Sin contrato, quien llama va
a leer tu código; con un contrato falso, va a programar contra algo que no
existe y el fallo aparecerá lejos de la causa. Si no estás seguro de que
garantizas algo, no lo garantices: ponlo en «Qué NO expone».

---

## `worklog/EVENTS.jsonl`

Una línea JSON por evento, **añadida** al final. Ejemplo de una vida real de un
carril, con una corrección incluida:

```jsonl
{"ts":"2026-08-18T22:40:00Z","carril":"NUCLEO","agente":"claude-1","evento":"abre","estado":"EN_CURSO","resumen":"Toma NUCLEO: guardia de monotonía temporal e invariancia al muestreo","refs":["R-14","R-22"],"bloqueos":[]}
{"ts":"2026-08-18T23:10:00Z","carril":"NUCLEO","agente":"claude-1","evento":"publica_contrato","estado":"EN_CURSO","resumen":"Contrato v1: Sample, PlayerKinematics, PossessionTracker, build_report","refs":["worklog/NUCLEO/CONTRATO.md"],"bloqueos":[]}
{"ts":"2026-08-18T23:55:00Z","carril":"NUCLEO","agente":"claude-1","evento":"entrega","estado":"LISTO_PARA_REVISION","resumen":"update() rechaza t no monotono; prueba de invariancia con frame_skip 0/2/5","refs":["R-14"],"bloqueos":[]}
{"ts":"2026-08-19T09:05:00Z","carril":"NUCLEO","agente":"claude-2","evento":"revisa","estado":"EN_CURSO","resumen":"Devuelto: la prueba de invariancia fija frame_skip=2 en dos de los tres casos","refs":["R-14"],"bloqueos":[]}
{"ts":"2026-08-19T09:40:00Z","carril":"NUCLEO","agente":"claude-1","evento":"corrige","estado":"LISTO_PARA_REVISION","resumen":"Parametriza la prueba sobre los tres valores de verdad","refs":["2026-08-19T09:05:00Z"],"bloqueos":[]}
{"ts":"2026-08-19T10:20:00Z","carril":"NUCLEO","agente":"claude-2","evento":"revisa","estado":"HECHO","resumen":"Definicion de Hecho verificada punto por punto","refs":[],"bloqueos":[]}
```

Fíjate en el evento `corrige`: lleva en `refs` el `ts` del evento que corrige. La
línea equivocada sigue ahí. Eso es lo que permite reconstruir por qué se hizo
algo, y no sólo qué quedó.

Un evento de bloqueo:

```jsonl
{"ts":"2026-08-19T11:00:00Z","carril":"OPERACION","agente":"claude-3","evento":"bloquea","estado":"BLOQUEADO","resumen":"No puedo escribir la politica de retencion sin saber si los videos se pueden guardar","refs":["A-02","R-30"],"bloqueos":["A-02 sin responder"]}
```

---

## Tabla de estados de carril

Fuente de verdad de las transiciones. El código que las valide debe leerlas de
aquí como dato, no reimplementarlas como condicionales.

| Desde | Hacia | Condición |
|---|---|---|
| `NO_INICIADO` | `EN_CURSO` | `tomar-carril` completo: dependencias con contrato publicado y nadie más en el carril |
| `EN_CURSO` | `LISTO_PARA_REVISION` | criterio de cierre demostrado por una prueba que pasa |
| `EN_CURSO` | `BLOQUEADO` | `bloqueos` no vacío |
| `BLOQUEADO` | `EN_CURSO` | el bloqueo se resolvió; la línea de evento lo dice |
| `LISTO_PARA_REVISION` | `HECHO` | otro agente verificó la definición de «Hecho» entera |
| `LISTO_PARA_REVISION` | `EN_CURSO` | la revisión devolvió trabajo, con la lista de qué falta |

Cualquier otra transición es un error. En particular no existe
`EN_CURSO → HECHO`: nadie aprueba su propio trabajo.
