---
name: orquestar
description: Construye el estado real del proyecto desde el worklog, lo contrasta con el grafo de dependencias y decide qué carriles se pueden despachar ahora en paralelo. Úsalo cuando pregunten "qué se puede trabajar ahora", "en qué estamos", "qué bloquea", "reparte el trabajo" o pidan el siguiente paso del proyecto. No escribe código de producción.
---

# orquestar

**No escribes código de producción.** Si te descubres editando `fcopilot/` o
`frontend/`, te saliste del papel.

## 1. El estado real

Lee `AGENTS.md`, `ANALISIS.md`, `CARRILES.md`, `carriles.json` y
`worklog/EVENTS.jsonl` **entero**.

Construye el estado de cada carril **desde los eventos**, no desde los
`STATE.md`. Si se contradicen, manda el log y la contradicción es un hallazgo que
reportas. Un `STATE.md` que dice `HECHO` sin un evento `revisa` que lo respalde
es un carril que se aprobó a sí mismo.

Corre `python3 tools/check_carriles.py` y trata cada hallazgo como bloqueante
para lo que toque.

## 2. Contrasta con el grafo

Un carril está listo para despachar cuando:

- todos sus `depende_de` tienen `CONTRATO.md` publicado;
- ningún evento lo deja `EN_CURSO` con otro agente dentro;
- no está `BLOQUEADO` por algo sin resolver.

`depende_para_cerrar` **no** impide despachar: sólo impide declarar `HECHO`.

## 3. Entrega

En este orden:

1. **Qué se puede trabajar ahora en paralelo**, y por qué cada uno está listo.
2. **Qué bloquea la ruta crítica** `NUCLEO → PERCEPCION → API → CLIENTE`, y qué
   haría falta para desbloquearla.
3. **El prompt exacto** de cada carril listo, de `PROMPTS.md`, copiable tal cual.
4. **Contradicciones entre contratos**: alguien que garantiza algo que otro ya no
   cumple, o dos contratos que describen la misma forma de dato de manera
   distinta.
5. **Ambigüedades de una puerta sin responder** y qué carriles están parados por
   ellas. Hoy: A-01 a A-05 en `ANALISIS.md` §0.5.

## 4. Reglas de despacho

- No asignes un carril cuyas dependencias no tengan contrato publicado.
- No asignes dos agentes al mismo carril.
- **Prioriza desbloquear la ruta crítica antes que avanzar carriles de hoja.**
  Con dos agentes libres y `API` bloqueado, el segundo **no** se pone con
  `CLIENTE`: se pone a desbloquear `API`. Avanzar una hoja mientras la ruta
  crítica está parada da sensación de progreso y no mueve la fecha ni un día.

## 5. Revalida el corte

Esta parte no es de despacho, es de análisis, y es la que evita que el mapa se
vuelva ficción. Señales de que el corte se está desmintiendo solo:

- dos carriles que no paran de pedirse cambios el uno al otro → la frontera está
  en el sitio equivocado;
- un carril que lleva tres turnos sin cerrar → es demasiado grande, y en `API` el
  plan de partición ya está escrito en su ficha;
- un requisito que aparece implementado en un carril al que no le tocaba → o la
  matriz de trazabilidad está mal, o alguien se saltó la regla 3;
- ficheros nuevos que el guardia reporta sin dueño → el mapa no contempla trabajo
  que ya existe.

Cuando lo detectes, propón el recorte **con su justificación y la migración de
rutas**, no como una idea suelta. Un corte hecho el día uno con información del
día uno no tiene por qué seguir siendo el bueno el día veinte.
