# API — estado

| | |
|---|---|
| **Estado** | LISTO_PARA_REVISION |
| **Último agente** | claude (turno 1 de API) |
| **Última actualización** | 2026-08-18T23:40:00Z |
| **Contrato publicado** | sí — `worklog/API/CONTRATO.md` v1 |
| **Depende de** | `NUCLEO` v1 y `PERCEPCION` v1 (ambos **publicados**); `PLATAFORMA` para cerrar |
| **Requisitos asignados** | R-08, R-10, R-13, R-15, R-17, R-19, R-21, R-24, R-25, R-27, R-28 |

## Qué está hecho

- Dieciséis rutas HTTP más el WebSocket, con estado aislado por `session_id`,
  persistencia comprimida y atómica, TTL y desalojo por límite de sesiones.
- Validación de configuración con vocabularios cerrados y rangos por clave.
- `validate_model_path` con `Path.is_relative_to`, que cerró un agujero real: el
  `startswith` anterior aceptaba directorios hermanos de `MODEL_ROOT`, y un `.pt`
  es un pickle.

Y en este turno:

- **El guardia de la regla 6** (R-15): `test_toda_ruta_de_sesion_declara_la_dependencia_de_sesion`
  recorre las rutas registradas de verdad en la aplicación y falla si alguna
  llega al estado sin la dependencia de sesión. Comprobado por mutación: una
  ruta `/api/fuga` que lee `session_manager` directamente tumba la suite.
- **Credencial opcional** (R-27): `API_KEY` por middleware —no ruta a ruta, para
  que una ruta nueva venga cubierta sin acordarse—, comparación en tiempo
  constante, cabecera o query string, `/health` abierto, y aviso al arrancar sin
  autenticación.
- **Límite global de análisis simultáneos** (R-28): `MAX_CONCURRENT_ANALYSES`.
  El lease por sesión impedía dos análisis en la misma sesión; nada impedía que
  doce sesiones ocuparan doce ficheros temporales de 1 GB compitiendo por dos
  hilos.
- **Corregido un bug que destapó el cambio de `PERCEPCION`**: el WebSocket pasaba
  `time.monotonic() - started` como si fuera tiempo de vídeo, así que las
  métricas de webcam se habrían etiquetado como comparables con las de fichero.
- **Protocolo NDJSON documentado** en el contrato, incluida la línea de error a
  mitad de stream.
- `limits` en `/health`, para que `CLIENTE` y `OPERACION` lean los topes en vez
  de suponerlos.

## Qué falta

1. **Verificación cruzada** (`revisar-carril`) por un agente que no sea este.
2. **A-01 sigue sin responder.** La credencial existe y viene apagada: encenderla
   es una variable de entorno, no un desarrollo. Lo que **no** está resuelto es
   que `session_id` siga sin ser identidad: dos clientes con la misma credencial
   se ven las sesiones entre sí, y `/api/sessions` enumera las de todos. Si la
   respuesta a A-01 es «expuesto», eso es trabajo de verdad, no una variable.
3. **Sin límite por cliente** (la mitad de R-28 que falta): nada impide abrir
   sesiones nuevas sin parar. Requiere identidad, así que depende de A-01.
4. Versionar `serialize_state`/`load_state`: hoy un cambio de formato rompe en
   silencio las sesiones guardadas de quien tenga un partido a medias.

## Bloqueos activos

- **A-01 sin responder** limita el punto 2 y bloquea el 3. El resto del carril
  avanzó igual, que era lo correcto: bloquear el carril entero por una pregunta
  que sólo afecta a una parte habría parado la ruta crítica sin motivo.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | `fcopilot/config.py` es de este carril | Es la superficie de configuración que la API valida y expone | sí | Moverlo a `NUCLEO` (D-04) |
| 2 | Si el carril no cierra en un turno, se parte sacando `fcopilot/sessions.py` | Tiene contrato distinto —ciclo de vida y persistencia— y rutas disjuntas | sí | No partirlo y aceptar turnos más largos |
| 3 | La credencial se implementa **apagada** en vez de esperar a A-01 | Encenderla pasa a ser una variable de entorno en vez de un desarrollo. Esperar habría dejado el servicio sin ninguna defensa y con la ruta crítica parada | sí | Quitar `API_KEY` y volver al servicio abierto |
| 4 | La credencial va por middleware, no por dependencia en cada ruta | Una ruta nueva queda protegida sin que su autor se acuerde: olvidarlo deja de ser posible | sí | Pasar a `Depends` por ruta y aceptar que se puede olvidar |
| 5 | `/health` responde sin credencial | Una sonda de vida que exige credencial no sirve de sonda de vida | sí | Protegerla y usar otra vía para el *liveness* |
| 6 | El límite de análisis simultáneos es global, no por cliente | No hay identidad de cliente que usar como clave. Un límite global protege el disco y los hilos, que es el daño real | sí, cuando haya identidad | Añadir el límite por cliente cuando A-01 se responda |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| ~~`NUCLEO`~~ | ~~Contrato de `build_report`~~ — resuelto: v1 | 2026-08-18 |
| ~~`PERCEPCION`~~ | ~~Contrato del analizador~~ — resuelto: v1 | 2026-08-18 |
| `CLIENTE` | Que envíe `X-Api-Key` cuando esté configurada, y que compruebe `"error" in linea` en **cada** línea del NDJSON, no sólo en la primera | 2026-08-18 |

## Notas para quien retome

- Es el carril más cargado del mapa y está en la ruta crítica. Si hay que
  acelerar el proyecto, se acelera aquí, y el plan de partición ya está decidido:
  no improvises otro.
- `get_session_id` sale de una cabecera o de un parámetro de consulta que **da el
  cliente**. Eso no es autenticación y no lo va a ser por mucho que se valide el
  formato: validar que un identificador tiene forma correcta no dice nada de
  quién lo envía.
- El `lifespan` restaura sesiones de disco al arrancar. Un cambio en
  `serialize_state`/`load_state` sin versión rompe las sesiones guardadas de
  quien actualice: si tocas el formato, versiónalo.
- `WorkerPool` tiene dos hilos por defecto y el análisis de vídeo es síncrono
  dentro de un hilo. Dos vídeos a la vez ya compiten; con `MAX_SESSIONS=12` el
  sistema prometía más concurrencia de la que puede dar. `MAX_CONCURRENT_ANALYSES`
  cierra esa promesa: por defecto vale lo mismo que `WORKER_THREADS`.
- **La lista `RUTAS_SIN_SESION` del test de auditoría lleva una justificación por
  ruta en la misma línea.** Está así a propósito: una excepción sin motivo escrito
  es la forma en que este tipo de guardia se vacía con el tiempo. Y hay un
  segundo test que falla si una excepción apunta a una ruta que ya no existe,
  porque una excepción huérfana esconde la siguiente.
- La plaza del semáforo se libera en tres sitios: el `finally` del generador, el
  `except BaseException` de la subida, y el 409 de sesión ocupada. Si añades otra
  salida temprana entre `acquire` y el `try`, acuérdate de liberarla o el
  servicio se queda sin plazas para siempre. Hay una prueba que lo comprueba para
  el caso de fichero inválido.
