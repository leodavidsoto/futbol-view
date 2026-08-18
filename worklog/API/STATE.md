# API — estado

| | |
|---|---|
| **Estado** | NO_INICIADO |
| **Último agente** | orquestador (intake y corte) |
| **Última actualización** | 2026-08-18T22:45:00Z |
| **Contrato publicado** | no |
| **Depende de** | `NUCLEO` y `PERCEPCION` (ninguno con contrato publicado); `PLATAFORMA` para cerrar |
| **Requisitos asignados** | R-08, R-10, R-13, R-15, R-17, R-19, R-21, R-24, R-25, R-27, R-28 |

## Qué está hecho

- Dieciséis rutas HTTP más el WebSocket, con estado aislado por `session_id`,
  persistencia comprimida y atómica, TTL y desalojo por límite de sesiones.
- Validación de configuración con vocabularios cerrados y rangos por clave.
- `validate_model_path` con `Path.is_relative_to`, que cerró un agujero real: el
  `startswith` anterior aceptaba directorios hermanos de `MODEL_ROOT`, y un `.pt`
  es un pickle.

## Qué falta

1. **El guardia de la regla 6** (R-15): un test que recorra las rutas registradas
   en la aplicación FastAPI y falle si alguna no declara la dependencia de sesión.
   **Hazlo primero**: es barato y protege todo lo demás que escribas después.
2. **Autenticación** (R-27). Hoy no hay ninguna y `CORS_ALLOW_ORIGINS` es `*`: el
   `session_id` lo elige el cliente, así que quien adivine uno lee el partido de
   otro. **Depende de A-01, sin responder.**
3. **Documentar el protocolo NDJSON** de `/api/process-video` en el contrato,
   incluida la línea `{"error": ...}` a mitad de stream, que hoy el cliente maneja
   por costumbre y no por contrato.
4. **Límites** (R-28): 1 GB por subida, sin tope acumulado ni por cliente.

## Bloqueos activos

- **Esperando los contratos de `NUCLEO` y `PERCEPCION`.**
- **A-01 sin responder** bloquea el punto 2, no el resto del carril.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | `fcopilot/config.py` es de este carril | Es la superficie de configuración que la API valida y expone | sí | Moverlo a `NUCLEO` (D-04) |
| 2 | Si el carril no cierra en un turno, se parte sacando `fcopilot/sessions.py` | Tiene contrato distinto —ciclo de vida y persistencia— y rutas disjuntas | sí | No partirlo y aceptar turnos más largos |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| `NUCLEO` | Contrato de `build_report`, para fijar la forma de `/api/report` | 2026-08-18 |
| `PERCEPCION` | Contrato del analizador y de `DetectorUnavailable` | 2026-08-18 |

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
  sistema promete más concurrencia de la que puede dar.
