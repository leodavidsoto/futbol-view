# PERCEPCION — estado

| | |
|---|---|
| **Estado** | LISTO_PARA_REVISION |
| **Último agente** | claude (turno 1 de PERCEPCION) |
| **Última actualización** | 2026-08-19T21:40:00Z |
| **Contrato publicado** | sí — `worklog/PERCEPCION/CONTRATO.md` v1 |
| **Depende de** | `NUCLEO` (contrato v1 **publicado**); `PLATAFORMA` para cerrar |
| **Requisitos asignados** | R-01, R-02, R-03, R-16 |

## Qué está hecho

- Detección con YOLO y opcionalmente SAHI, con importación opcional y
  `DetectorUnavailable` en la llamada, no en el import.
- Tres trackers: Norfair, ByteTrack y un tracker de centroides propio de respaldo.
- Clasificación de equipos con centroides ordenados de forma determinista y voto
  por track acumulado en ventana, que arregló el intercambio `team_1`/`team_2`
  entre reajustes.

Y en este turno:

- **Cerrado el agujero real de la regla 5**, que era la solicitud de `NUCLEO`:
  `analyzer.py` declara la fuente de tiempo, impide mezclar vídeo con reloj
  (`TimeBaseError`), la expone en `stats.time_source` y la propaga hasta
  `meta.time_source` del informe.
- **Cobertura del camino normal**: `tests/test_detection.py` (12 pruebas) y
  `tests/test_osnet.py` (13) nuevos. `osnet` 15 % → 31 %, `detection` 75 % → 81 %.
- **Extremos de la ventana de votos** y determinismo del orden de centroides:
  13 pruebas nuevas en `tests/test_teams.py`. `teams` 85 % → 87 %.
- **Cruce de jugadores**: cuatro pruebas que fijan que dos jugadores que se
  superponen conservan identidad, no generan saltos rechazados y no cambian de
  equipo.

### Turno de la fusión de tracklets

El tracker producía **51 identidades para unos 22 jugadores** en el partido real.
`fcopilot/tracklets.py` cose los trozos con tres filtros —tiempo, física y
apariencia— que hay que pasar todos, igual que el post-proceso del pipeline
ganador de SoccerNet GSR.

Lo delicado no se ve: al coser **no se calcula ningún tramo entre los dos
trozos**. Un hueco de 2 s con 15 m son 27 km/h, por debajo del filtro de saltos
imposibles: se colarían sin que nada los delatara.

Un fallo grave encontrado escribiéndolo: el coste normalizaba la distancia por
un radio que crece con el hueco, así que **saltarse un trozo salía más barato
que unirse al de al lado**. Con cuatro trozos consecutivos producía 1→3 y 2→4:
dos jugadores donde había uno, con la mitad de los metros cada uno.

Los tres clasificadores exponen ahora `describe()`. El analizador acumula una
media incremental por track —no una lista, que crecería sin tope—.

## Qué falta

### De la revisión cruzada de código (2026-08-19)

1. **`apply_config` reinicia el tracker sin limpiar `self.tracks`.** Los IDs
   vuelven a empezar en 1, así que un jugador nuevo hereda la cinemática, el
   nombre y el equipo de otro. Es de los que producen datos plausibles y falsos,
   que son los peores.
2. **`load_state` fija `_t_origin = 0.0`.** Una sesión de webcam restaurada
   calcula `t = time.monotonic()` y suma de golpe el tiempo de arranque de la
   máquina a los segundos de posesión y al tiempo activo.
3. **`teams._fit_features` sólo reinicia `_since_fit` al tener éxito.** Si los
   centroides se quedan más cerca que `min_separation`, se lanza un KMeans
   completo en **cada** `predict()` —unas 22 por frame— y `_features` crece sin
   límite.

Ninguno tiene todavía prueba que lo fije.

### Lo de siempre

4. **Verificación cruzada** (`revisar-carril`) por un agente que no sea este.
2. `resolve_tracker_type` sigue degradando en silencio (ver notas). El valor
   efectivo viaja en `stats.tracker`, pero nadie avisa al usuario de que pidió
   Norfair y le dieron el tracker de centroides.
3. Las líneas 44-180 de `osnet.py` —la red en sí— sólo se ejecutan con `torch`
   instalado. Es la excepción de cobertura declarada; el resto del módulo ya se
   prueba con embeddings sintéticos.

### Lo que sigue sin resolver aquí

- **El balón.** Sigue siendo el techo: a esta distancia son cuatro píxeles y ni
  YOLO ni el modelo de fútbol lo ven de forma fiable. La vía es inferencia por
  teselas específica de balón (la pieza SAHI ya está, pensada para personas) o
  un modelo dedicado. Ver `INVESTIGACION.md` §4.
- **La apariencia sin `torch` es el color del kit**, que distingue entre equipos
  y no entre compañeros. Filtra fusiones absurdas; no resuelve las difíciles.

## Bloqueos activos

- ninguno.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | `fcopilot/analyzer.py` es de este carril | Manda el bucle de frames, no la definición de métrica | sí, pero cara si el fichero crece | Partirlo en bucle y ensamblador (D-05) |
| 2 | La fuente de tiempo se fija en la primera llamada y no puede cambiar | Mezclar tiempo de vídeo con reloj dentro de un análisis produce métricas incomparables sin que nada falle. Prohibirlo es barato; detectarlo después es imposible | sí | Permitir el cambio y aceptar que las métricas mezcladas no significan nada |
| 3 | Sin `timestamp` se sigue permitiendo el reloj, en vez de exigirlo siempre | En directo no existe un tiempo de vídeo que consultar. Prohibir el reloj rompería la webcam, que es un caso de uso real | sí | Exigir `timestamp` y que el llamador de webcam construya el suyo |
| 4 | Los embeddings de OSNet se prueban sintéticos, no con la red | Meter `torch` en CI son varios gigabytes y rompe la regla 7. Lo que falla en la práctica no es la red sino la lógica que la rodea | sí | Un job de CI aparte con `torch`, si alguna vez compensa |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| ~~`NUCLEO`~~ | ~~Contrato publicado~~ — resuelto: v1 publicada | 2026-08-18 |

## Notas para quien retome

- El detector guionizado de `tests/conftest.py` es de `PLATAFORMA`: si necesitas
  otra forma de doble, pídesela en vez de editarlo.
- La bandera `*_AVAILABLE` de cada dependencia es lo que hace que CI pueda correr
  sin gigabytes. Cualquier `import` que saques del `try` rompe el build de todos
  los carriles a la vez, no sólo el tuyo.
- `resolve_tracker_type` degrada silenciosamente a otro tracker si el pedido no
  está disponible. Es cómodo y es una trampa: el usuario cree que está usando
  Norfair y está usando el de centroides. El valor efectivo ya viaja en
  `stats.tracker` de cada frame, así que el dato está; lo que falta es que
  alguien lo mire y avise. Queda para `CLIENTE`.
- **El primer frame de un track no sale en la respuesta**: el tracker necesita
  un frame para confirmarlo. No es una pérdida, es el calentamiento, y cualquier
  prueba sobre secuencias tiene que descontarlo — me costó un rato entender por
  qué el frame 0 daba cero jugadores.
- **Cuidado con la velocidad al escribir escenarios sintéticos.** El primer
  guion de cruce que escribí movía a los jugadores 12 px por frame: a 25 fps y
  8 px/m son 135 km/h, muy por encima de `max_speed_kmh`, así que *todos* los
  tramos se rechazaban y la prueba medía el rechazo en vez del cruce. A 3 px por
  frame son ~34 km/h, que es rápido pero posible.
- Los embeddings sintéticos de `test_osnet.py` se construyen con
  `np.random.default_rng(semilla)` y vectores unitarios separables. Si cambias
  `min_separation` o el umbral de similitud de `_refit`, esas pruebas son las
  que te van a decir que lo hiciste.
