# worklog/

El relevo. Aquí vive lo que un agente necesita para retomar un carril sin haber
visto nunca este proyecto.

## Qué hay

| Ruta | Qué es | Quién escribe |
|---|---|---|
| `EVENTS.jsonl` | El log global, en orden. Una línea JSON por turno | todos, **sólo añadiendo** |
| `<CARRIL>/STATE.md` | El estado vivo de un carril | el agente de ese carril |
| `<CARRIL>/CONTRATO.md` | Lo que ese carril promete a los demás | el agente de ese carril |

## Reglas de escritura

1. **`EVENTS.jsonl` es de sólo añadir.** Nunca edites ni borres una línea previa,
   ni siquiera para corregir un error tuyo. Un error se corrige con un evento
   `corrige` que lleva en `refs` el `ts` del evento equivocado. El guardia
   rechaza cualquier diff que elimine líneas de este fichero.
2. **Una línea por turno.** Si tu turno hizo tres cosas, la línea las resume en
   una frase; el diff cuenta el resto.
3. **`STATE.md` se sobrescribe**, a diferencia del log: describe el presente, no
   la historia. La historia está en los eventos.
4. **Cada carril escribe sólo en su directorio.** `worklog/<CARRIL>/**` pertenece
   a ese carril; `README.md` y `EVENTS.jsonl` son de `PLATAFORMA` (con la
   excepción de añadir líneas al log, que es de todos).
5. **Si el log y el `STATE.md` se contradicen, manda el log**, y la
   contradicción es un hallazgo que el orquestador tiene que reportar.

Los formatos exactos están en `PLANTILLAS.md`. El significado de cada estado y
las transiciones válidas, en `AGENTS.md`.

## Cómo se lee esto por primera vez

`EVENTS.jsonl` **entero**, no las últimas líneas. El orden es lo que cuenta la
historia: qué se intentó, qué se devolvió en revisión y por qué algo está como
está. Después, el `STATE.md` de tu carril, y en particular sus dos últimas
secciones —decisiones y notas—, que son las que dicen lo que el código no dice.
