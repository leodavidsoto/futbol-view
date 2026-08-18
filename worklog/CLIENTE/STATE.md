# CLIENTE — estado

| | |
|---|---|
| **Estado** | EN_CURSO |
| **Último agente** | claude (turno 1 de CLIENTE) |
| **Última actualización** | 2026-08-18T23:55:00Z |
| **Contrato publicado** | sí — `worklog/CLIENTE/CONTRATO.md` v1 |
| **Depende de** | `API` v1 (**publicado**); `PLATAFORMA` para cerrar |
| **Requisitos asignados** | R-06, R-11, R-12 |

## Qué está hecho

- `session_id` por pestaña en `sessionStorage`: antes todas las pestañas
  compartían la sesión `default` y se pisaban los datos.
- Búsqueda binaria del frame por tiempo de vídeo, en vez de recorrido lineal.
- Object URLs liberados y errores del backend visibles en vez de tragados.
- 65 pruebas sobre las funciones puras de `src/lib/`.

Y en este turno, cuatro extracciones de `App.jsx` (1915 → **1271** líneas):

| Módulo nuevo | Líneas | Pruebas |
|---|---|---|
| `render/scene.js` — dibujo del overlay, funciones puras | 345 | 31 |
| `components/index.jsx` — componentes de presentación | 214 | — |
| `styles.js` — estilos en línea | 178 | — |
| `lib/interaction.js` — ratón → canvas, jugador bajo el cursor | 50 | 13 |

Y las dos solicitudes que dejó `API`:

- **Credencial**: `apiFetch` manda `x-api-key` y `wsStreamUrl` la pone en el
  query string (un WebSocket del navegador no admite cabeceras propias). Vacía
  por defecto: el uso local no cambia. 6 pruebas.
- **Error por línea del NDJSON**: ya estaba bien, dentro del bucle de frames.
  Comprobado y anotado en el contrato, que es donde faltaba.

115 pruebas de frontend (antes 65), lint limpio y `npm run build` en verde.

## Qué falta — **el carril NO cierra**

El criterio de cierre es «`App.jsx` por debajo de 400 líneas» y está en 1271.
Falta lo más grande, y no se hizo por una razón, no por tiempo:

1. **El panel derecho** (401 líneas de JSX) necesita ~35 props si se extrae tal
   cual. Un componente de 35 props no es mejor diseño que el monolito: sólo
   mueve el problema y añade una capa de indirección. La extracción correcta es
   **con** su estado —un `useDetectorConfig` que agrupe los doce `useState` del
   detector, y un contexto o reductor para lo demás—, y eso es rediseño, no
   troceado.
2. **La lógica de vídeo y streaming** (~200 líneas: carga, detección del primer
   frame, análisis, pausa/reanudación, reproducción) sale limpia a un
   `useVideoAnalysis`, pero comparte seis refs con el resto del componente.
3. **Pruebas de componente.** Las 115 siguen siendo de módulo: ninguna monta un
   componente. Falta `@testing-library/react` en las dependencias.

## Bloqueos activos

- ninguno. Lo que falta es trabajo, no espera.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | Este carril publica contrato aunque sea una hoja | Declarar qué parte del contrato de `API` consume es lo que le dice a `API` qué no puede romper | sí | Dejar de publicarlo y descubrir las roturas en producción |
| 2 | Se extrae primero el dibujo, no la interfaz | Es el bloque más grande sin nada de React y por tanto el único que se podía probar de verdad sin montar la aplicación. 31 pruebas de una tacada | sí | — |
| 3 | **No** se extrae el panel derecho a un componente de 35 props | Mover 400 líneas a un fichero con 35 props no reduce el acoplamiento, lo documenta. La extracción buena agrupa el estado primero | sí | Hacerlo igualmente si sólo importa la cuenta de líneas |
| 4 | La credencial se lee de `VITE_API_KEY` al cargar el módulo | Es configuración de despliegue, no de sesión: no cambia en caliente | sí | Leerla de un estado si alguna vez hace falta cambiarla sin recargar |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| ~~`API`~~ | ~~Contrato del protocolo NDJSON~~ — resuelto: v1 | 2026-08-18 |
| `API` | Que `video_time` siga siendo **monótono creciente**: la sincronización del overlay es una búsqueda binaria sobre el búfer y, si dejara de serlo, se desincronizaría sin ningún error visible | 2026-08-18 |

## Notas para quien retome

- Corte sugerido, no vinculante: reproducción y sincronización de frames,
  configuración del detector, calibración, y anotación de jugadores son cuatro
  grupos de estado que casi no se hablan. Empieza por el que menos dependencias
  tenga; no intentes los cuatro en un turno.
- Tres requisitos asignados es el recuento más bajo del mapa y el trabajo es de
  los mayores. La cuenta de requisitos mide responsabilidad, no esfuerzo.
- `FootballCopilot_v2.jsx` de la raíz **no es este carril** y está congelado: es
  código muerto pendiente de A-05. Si te lo encuentras, no lo edites.
- **El espía del contexto 2D de `render/__tests__/scene.test.js` captura el
  color en el momento de la llamada, no al final.** `fillStyle` es mutable: si
  lo miras cuando la prueba termina, todas las llamadas parecen del último
  color. Me costó una prueba en verde que no probaba nada.
- Escribí una prueba que afirmaba que «ninguna capa opcional se dibuja por
  defecto» y falló: **los nombres sí vienen activados por defecto**, igual que
  en la aplicación. La premisa era mía, no del código. La prueba ahora comprueba
  lo concreto: ni barra de posesión ni mini-mapa.
- El canvas se dibuja a 854×480 y se muestra escalado. `canvasPointFromEvent`
  hace esa conversión y tiene prueba con el canvas a la mitad: sin ella, en una
  ventana estrecha se seleccionaba el jugador equivocado.
