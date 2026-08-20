---
name: cerrar-turno
description: Ritual de cierre obligatorio de un turno en un carril de este repositorio. Úsalo SIEMPRE antes de terminar de trabajar en PLATAFORMA, NUCLEO, PERCEPCION, API, CLIENTE u OPERACION, incluso si no terminaste el trabajo o te quedaste bloqueado. Actualiza STATE.md, añade una línea a EVENTS.jsonl, comprueba la propiedad de rutas, commitea y pushea.
---

# cerrar-turno

**Obligatorio.** Incluso si no terminaste. Incluso si te bloqueaste a los diez
minutos. Un turno sin cerrar deja el carril marcado `EN_CURSO` para siempre y
nadie más se atreve a entrar.

## 1. Comprueba antes de escribir nada

```bash
python3 tools/check_carriles.py --diff origin/main --carril <TU_CARRIL>
```

Si te dice que tocaste ficheros de otro carril, **no lo justifiques: deshazlo**.
Lo que necesitabas allí va como solicitud en el `STATE.md` de ese carril, en su
tabla «Solicitudes a otros carriles».

Y corre lo que toque: `pytest`, y `npm test` + `npm run lint` si tocaste
`frontend/`. Entregar en rojo es entregarle el problema al siguiente.

## 2. Actualiza `STATE.md`

Con el estado **real**, no el que te gustaría:

- `EN_CURSO` si sigue abierto, `LISTO_PARA_REVISION` si cumples el criterio de
  cierre, `BLOQUEADO` si algo te para —y entonces `bloqueos` no puede ir vacío—.
- **Nunca `HECHO`.** Ese estado lo pone otro agente, en `revisar-carril`. Nadie
  aprueba su propio trabajo.
- Qué está hecho, con el fichero o la prueba que lo demuestra.
- Qué falta, **en el orden en que lo haría quien retome**.
- La tabla de decisiones, con la columna de reversibilidad rellenada de verdad:
  «sí», «no» o «cara», y qué la revertiría.
- Las notas para quien retome.

Sobre las notas: escribe lo que **no se deduce leyendo el diff**. Que probaste
algo y no funcionó y por qué. Que ese `round()` está ahí por una razón. Que el
caso raro que parece un descuido es deliberado. Una nota que repite lo que se ve
en el diff es ruido: bórrala.

## 3. Una línea en `EVENTS.jsonl`

**Una**, añadida al final, nunca reescribiendo las previas:

```json
{"ts":"<ISO-8601 UTC>","carril":"<CARRIL>","agente":"<quién>","evento":"<avanza|publica_contrato|entrega|bloquea|corrige>","estado":"<estado real>","resumen":"<una frase>","refs":["<IDs>"],"bloqueos":[]}
```

Si tu turno hizo tres cosas, la frase las resume; el diff cuenta el resto. Si
estás corrigiendo un error de un turno anterior, el evento es `corrige` y lleva
en `refs` el `ts` del evento equivocado: la línea equivocada se queda donde
está. Las correcciones no borran historia.

## 4. Commit y push

```bash
git add -A
git commit -m "<carril>: <qué cambió y por qué>"
git push -u origin <rama>
```

**El push va en este skill a propósito.** Un relevo que vive sólo en tu disco
local no es un relevo: el siguiente agente arranca en otra máquina, o en otro
contenedor, y lo único que va a ver es lo que esté en el remoto.

## 5. Di dónde lo dejaste

Cierra tu mensaje con: el estado del carril, qué es lo siguiente que haría quien
retome, y qué decisiones tomaste tú que alguien debería mirar.
