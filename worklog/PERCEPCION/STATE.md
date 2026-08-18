# PERCEPCION — estado

| | |
|---|---|
| **Estado** | NO_INICIADO |
| **Último agente** | orquestador (intake y corte) |
| **Última actualización** | 2026-08-18T22:45:00Z |
| **Contrato publicado** | no |
| **Depende de** | `NUCLEO` (contrato **no publicado** — no se puede abrir todavía); `PLATAFORMA` para cerrar |
| **Requisitos asignados** | R-01, R-02, R-03, R-16 |

## Qué está hecho

- Detección con YOLO y opcionalmente SAHI, con importación opcional y
  `DetectorUnavailable` en la llamada, no en el import.
- Tres trackers: Norfair, ByteTrack y un tracker de centroides propio de respaldo.
- Clasificación de equipos con centroides ordenados de forma determinista y voto
  por track acumulado en ventana, que arregló el intercambio `team_1`/`team_2`
  entre reajustes.

## Qué falta

1. **Cobertura del camino normal**: `osnet.py` al 15 %, `detection.py` al 75 %.
   Hoy la degradación está probada y el funcionamiento normal no. Con dobles, sin
   meter `torch` en CI.
2. **Extremos de la ventana de votos**: un track con un solo voto, uno con la
   ventana llena y empate, uno que cambia de equipo a mitad.
3. **Cruce de jugadores**: secuencia sintética con dos jugadores que se cruzan →
   dos tracks estables, ninguna reasignación de equipo. Es el caso que rompe
   todos los trackers y no está probado.

## Bloqueos activos

- **Esperando el contrato de `NUCLEO`.** No es un obstáculo que rodear: es la
  regla 1 funcionando.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | `fcopilot/analyzer.py` es de este carril | Manda el bucle de frames, no la definición de métrica | sí, pero cara si el fichero crece | Partirlo en bucle y ensamblador (D-05) |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| `NUCLEO` | Contrato publicado de `Sample` y `PlayerKinematics` | 2026-08-18 |

## Notas para quien retome

- El detector guionizado de `tests/conftest.py` es de `PLATAFORMA`: si necesitas
  otra forma de doble, pídesela en vez de editarlo.
- La bandera `*_AVAILABLE` de cada dependencia es lo que hace que CI pueda correr
  sin gigabytes. Cualquier `import` que saques del `try` rompe el build de todos
  los carriles a la vez, no sólo el tuyo.
- `resolve_tracker_type` degrada silenciosamente a otro tracker si el pedido no
  está disponible. Es cómodo y es una trampa: el usuario cree que está usando
  Norfair y está usando el de centroides. Si lo tocas, que al menos quede en el
  resultado.
