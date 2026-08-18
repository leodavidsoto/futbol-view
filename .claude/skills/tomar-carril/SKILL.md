---
name: tomar-carril
description: Ritual de apertura de un turno de trabajo en un carril de este repositorio. Úsalo al empezar a trabajar en PLATAFORMA, NUCLEO, PERCEPCION, API, CLIENTE u OPERACION, o cuando te pidan "toma el carril X", "empieza el carril X" o te pasen un prompt de PROMPTS.md. Verifica que las dependencias tengan contrato publicado, que nadie más esté dentro, y marca el carril EN_CURSO.
---

# tomar-carril

No empieces a escribir código hasta terminar estos cinco pasos. El objetivo es
que no arranques a ciegas ni pises a otro agente.

## 1. Contexto, en este orden

- `AGENTS.md` — las siete reglas innegociables y la definición de «Hecho».
- `ANALISIS.md` — el catálogo de requisitos y las ambigüedades abiertas (§0.5).
- `CARRILES.md` — el mapa, y la ficha de tu carril: rutas propias y criterio de cierre.
- `worklog/EVENTS.jsonl` — **entero**, no las últimas líneas. El orden cuenta la historia.

## 2. El estado de tu carril

Lee `worklog/<CARRIL>/STATE.md` completo, y en particular sus dos últimas
secciones: **decisiones** (con su columna de reversibilidad) y **notas para quien
retome**. Son las que dicen lo que el código no dice. Si la nota te ahorra
repetir un experimento fallido, ya se pagó sola.

Si el `STATE.md` y los eventos se contradicen, **manda el log** y la
contradicción es un hallazgo que tienes que reportar al cerrar.

## 3. Verifica las dependencias — este paso es el que importa

Para cada carril en `depende_de` de tu entrada en `carriles.json`, comprueba que
existe `worklog/<DEPENDENCIA>/CONTRATO.md`.

**Si falta uno, detente aquí.** No leas su código para deducir su interfaz, no
programes contra su implementación, no lo dejes «para ajustarlo después». Anota
el bloqueo en tu `STATE.md`, escribe la línea de evento con `estado: BLOQUEADO` y
`bloqueos` no vacío, y dilo.

Eso no es un obstáculo que rodear: es la regla 1 haciendo su trabajo. Un carril
construido contra una implementación se rompe la primera vez que esa
implementación cambia, y el fallo aparece lejos de la causa.

Las dependencias `depende_para_cerrar` **no bloquean el arranque**: son
necesarias para declararte `HECHO`, no para empezar.

## 4. Nadie más dentro

Recorre `EVENTS.jsonl` de atrás hacia adelante buscando el último evento de tu
carril. Si su `estado` es `EN_CURSO` y el `agente` no eres tú, hay otro agente
trabajando: no entres. Un carril, un agente, un turno.

Si el último evento es `LISTO_PARA_REVISION`, lo que toca no es implementar: es
`revisar-carril`, y lo hace alguien que no lo implementó.

## 5. Abre

Marca `EN_CURSO` en `STATE.md` y **añade** una línea a `worklog/EVENTS.jsonl`:

```json
{"ts":"<ISO-8601 UTC>","carril":"<CARRIL>","agente":"<quién eres>","evento":"abre","estado":"EN_CURSO","resumen":"<qué vas a intentar en este turno>","refs":["<IDs de requisito>"],"bloqueos":[]}
```

Añadir, nunca reescribir. Después, comprueba que partes de un sitio limpio:

```bash
python3 tools/check_carriles.py
```

Si ya sale con hallazgos antes de que toques nada, arréglalos o repórtalos: no
empieces encima de un repositorio que ya incumple sus propias reglas.
