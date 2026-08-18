# CLIENTE — estado

| | |
|---|---|
| **Estado** | NO_INICIADO |
| **Último agente** | orquestador (intake y corte) |
| **Última actualización** | 2026-08-18T22:45:00Z |
| **Contrato publicado** | no |
| **Depende de** | `API` (contrato no publicado); `PLATAFORMA` para cerrar |
| **Requisitos asignados** | R-06, R-11, R-12 |

## Qué está hecho

- `session_id` por pestaña en `sessionStorage`: antes todas las pestañas
  compartían la sesión `default` y se pisaban los datos.
- Búsqueda binaria del frame por tiempo de vídeo, en vez de recorrido lineal.
- Object URLs liberados y errores del backend visibles en vez de tragados.
- 65 pruebas sobre las funciones puras de `src/lib/`.

## Qué falta

1. **Partir `App.jsx`**: 1915 líneas, unos cuarenta `useState` en un solo
   componente. Es el mismo monolito que la PR #1 deshizo en el backend, en el
   lado que no se tocó. Criterio de cierre: por debajo de 400 líneas.
2. **Pruebas de componente.** Las 65 que hay no tocan ni un componente.

## Bloqueos activos

- **Esperando el contrato de `API`.**

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | Este carril publica contrato aunque sea una hoja | Declarar qué parte del contrato de `API` consume es lo que le dice a `API` qué no puede romper | sí | Dejar de publicarlo y descubrir las roturas en producción |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| `API` | Contrato del protocolo NDJSON, incluida la línea de error a mitad de stream | 2026-08-18 |

## Notas para quien retome

- Corte sugerido, no vinculante: reproducción y sincronización de frames,
  configuración del detector, calibración, y anotación de jugadores son cuatro
  grupos de estado que casi no se hablan. Empieza por el que menos dependencias
  tenga; no intentes los cuatro en un turno.
- Tres requisitos asignados es el recuento más bajo del mapa y el trabajo es de
  los mayores. La cuenta de requisitos mide responsabilidad, no esfuerzo.
- `FootballCopilot_v2.jsx` de la raíz **no es este carril** y está congelado: es
  código muerto pendiente de A-05. Si te lo encuentras, no lo edites.
