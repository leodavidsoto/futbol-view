# Contrato de CLIENTE

**Versión:** 1 · **Publicado:** 2026-08-18

`CLIENTE` es una hoja del grafo: nadie depende de él. Publica este documento
igualmente para declarar **qué parte del contrato de `API` consume**, que es lo
que le dice a `API` qué no puede romper sin avisar.

## Qué consume de `API` v1

| Qué | Dónde se usa | Qué pasa si cambia |
|---|---|---|
| `GET /api/config` | Al arrancar, para poblar el panel de detección | El panel queda con valores por defecto y aparece el aviso de error |
| `POST /api/config` | Cada cambio del panel | El ajuste no se aplica; se muestra el error |
| `GET`/`POST` `/api/calibrate` | Modo calibración de 4 puntos | La calibración deja de guardarse |
| `POST /api/player-name`, `/api/player-team` | Popup de anotación | Las correcciones se pierden al recargar |
| `POST /api/preview-frame` | Primer frame del vídeo | No hay vista previa: no se pueden asignar equipos antes de analizar |
| `POST /api/process-video` | El análisis entero | Es la ruta crítica de la aplicación |
| `GET /api/export` | Botón de exportar | — |
| `WS /ws/stream` | Modo webcam | — |

**Del protocolo NDJSON depende lo siguiente, y es lo más frágil:**

- Cada línea es un JSON completo. Se acumulan en un búfer hasta `MAX_BUFFERED_FRAMES`.
- `video_time` sincroniza el overlay con la reproducción, por **búsqueda binaria**
  sobre el búfer: exige que `video_time` sea **monótono creciente**. Si dejara de
  serlo, el overlay se desincronizaría sin ningún error visible.
- `{"error": ...}` se comprueba **en cada línea**, no sólo en la primera.
- De cada frame se usan `players[].{track_id,name,team,center,bbox,speed_kmh,total_dist_m,trail,world_pos}`,
  `ball.{center,bbox,trail,possession_pct,world_pos}` y `stats.*`.

## Qué expone hacia dentro del proyecto

Nada al backend. Dentro del propio carril, tres módulos que sí son reutilizables
y están probados:

| Módulo | Qué hace |
|---|---|
| `render/scene.js` | Dibujo del overlay: funciones puras `(ctx, data, opts)`. 31 pruebas |
| `lib/interaction.js` | Ratón → coordenadas del canvas y jugador bajo el cursor. 13 pruebas |
| `lib/frames.js` | Búsqueda binaria del frame por tiempo y troceado NDJSON |

## Qué NO garantiza

- **El overlay se dibuja en el tamaño del vídeo procesado** (854×480 por
  defecto) y se escala al mostrarlo. Cualquier coordenada que venga del backend
  está en ese sistema, no en píxeles de pantalla.
- **`App.jsx` sigue siendo un componente grande** (1271 líneas). Lo extraído está
  probado; lo que queda dentro, no.
- **No hay pruebas de integración de la aplicación montada.** Las 115 pruebas son
  de módulos.

## Qué necesita de `API`

- Que `video_time` siga siendo monótono creciente.
- Que la línea de error mantenga la clave `error` con un mensaje legible.
- Aviso antes de cambiar la forma de `players[]` o `ball`.
