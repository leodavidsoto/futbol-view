---
name: publicar-contrato
description: Escribe el CONTRATO.md de un carril de este repositorio, con esquemas concretos, tabla de errores y qué NO expone. Úsalo antes de implementar un carril del que dependan otros (NUCLEO, PERCEPCION, API), o cuando te pidan "publica el contrato" o "define la interfaz de X". Los demás carriles programan contra este documento, no contra tu código.
---

# publicar-contrato

Escribe `worklog/<CARRIL>/CONTRATO.md` siguiendo la plantilla de `PLANTILLAS.md`.

Publícalo **antes** de implementar, no después. Los carriles que dependen de ti
están parados hasta que exista, y en este proyecto la ruta crítica es
`NUCLEO → PERCEPCION → API → CLIENTE`: cada hora que tardas en publicar es una
hora que tres carriles no avanzan.

## Esquemas concretos, no descripciones

No sirve «devuelve las métricas del jugador». Sirve el diccionario con sus
claves, sus tipos y **sus unidades** —metros o píxeles, km/h o m/s, segundos o
frames—, porque la mitad de los errores de integración de este proyecto son de
unidad, no de forma.

Para una función: la firma completa, qué pasa con la entrada vacía, qué garantías
de orden das. Para una ruta HTTP: método, cuerpo de entrada, cuerpo de salida,
códigos. Para un stream: qué líneas pueden aparecer, **en qué posiciones**, y qué
significa que se corte.

## La tabla de errores

Por cada error: la situación, qué devuelves, y **qué debe hacer quien llama**. Esa
tercera columna es la que se olvida y la que de verdad sirve: «reintenta con otro
`session_id`» es útil; «error 409» no dice nada.

## Qué NO expone

La sección que más ahorra después. Aquí va lo que es interno y nadie puede
asumir: estructuras mutables que devuelves por referencia, orden que no
garantizas, campos que pueden faltar, valores que hoy son estables por accidente.

Si no estás seguro de garantizar algo, **no lo garantices**: ponlo aquí.

## Quién depende de esto

Lista los carriles y qué parte usa cada uno, sacándolo de `carriles.json`. Es lo
que te dice a quién avisar cuando cambies algo.

## La advertencia

**Un contrato que miente es peor que uno ausente.** Sin contrato, quien llama va
a leer tu código y va a acertar. Con un contrato falso, va a programar contra
algo que no existe, y el fallo va a aparecer lejos de la causa, semanas después,
en el carril de otro.

Antes de publicar, lee tu contrato al lado de tu código y pregúntate por cada
línea: ¿esto lo cumplo hoy, o es lo que pretendo cumplir?

## Al terminar

Evento `publica_contrato` en `EVENTS.jsonl` y `Contrato publicado: sí` en tu
`STATE.md`. Los carriles que te esperan comprueban justo eso.
