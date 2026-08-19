# Contrato de NUCLEO

**Versión:** 2 · **Publicado:** 2026-08-19 · **Estable desde:** 2026-08-18

Todo lo de aquí es importable desde `fcopilot` y no depende de FastAPI, OpenCV,
YOLO ni torch. Se puede ejercitar entero sin vídeo y sin modelo.

## Qué expone

### `Sample` — una posición observada

```python
@dataclass(frozen=True)
class Sample:
    frame: int                      # nº de frame del vídeo original
    t: float                        # SEGUNDOS DESDE EL INICIO DEL ANÁLISIS
    x: float; y: float              # píxeles del frame procesado
    wx: float | None = None         # metros en el campo, si hay homografía
    wy: float | None = None
```

**`t` es tiempo de vídeo, no de reloj.** Es la garantía de la que dependen todas
las demás: quien construya un `Sample` con `time.time()` obtiene métricas que
parecen correctas y no lo son. Inmutable (`frozen`), así que se puede compartir
sin copiar.

`has_world` es `True` sólo si `wx` **y** `wy` están presentes.

### `PlayerKinematics` — estado cinemático de un track

```python
kin = PlayerKinematics(track_id: int, config: KinematicsConfig | None)
kin.update(sample: Sample) -> float     # velocidad suavizada en km/h
kin.finalize() -> None                  # cierra un sprint en curso al terminar
kin.summary() -> dict
kin.trail(length: int = 20) -> list[dict]
kin.to_state() / PlayerKinematics.from_state(state, config) -> PlayerKinematics
```

Garantías de `update`:

| Garantía | Detalle |
|---|---|
| **Invariante al muestreo** | En movimiento rectilíneo uniforme, analizar 1 de cada N frames da la misma distancia y la misma velocidad. Fijado por `test_las_tres_frecuencias_dan_el_mismo_resultado` |
| **Sin doble conteo** | Cada tramo se acumula una vez, entre la muestra nueva y la inmediatamente anterior |
| **Tiempo monótono** | `t` menor que el anterior lanza `TimeBaseError`. `t` igual descarta la muestra y suma en `duplicate_samples` |
| **Saltos imposibles descartados** | Un tramo por encima de `config.max_speed_kmh` no acumula distancia ni tiempo activo; suma en `rejected_steps` |
| **Historial acotado** | Como mucho `config.max_history` muestras (300 por defecto); las viejas se descartan por el principio |

`summary()` devuelve, con estas unidades exactas:

```python
{
  "track_id": int,
  "total_dist_m": float,        # metros
  "speed_kmh": float,           # km/h, suavizada con EMA
  "max_speed_kmh": float,       # km/h
  "avg_speed_kmh": float,       # km/h sobre el tiempo activo, no el observado
  "sprints": int,
  "observed_s": float,          # segundos entre la primera y la última muestra
  "rejected_steps": int,        # saltos descartados: diagnóstico del tracking
  "duplicate_samples": int,     # muestras con t repetido
  "zones_m": {str: float},      # metros por zona, claves = nombres de SPEED_ZONES
}
```

**Unidad de la distancia:** metros reales si las muestras traen `wx`/`wy`;
metros estimados dividiendo píxeles entre `config.pixels_per_meter` si no. Si
unas muestras traen mundo y otras no, ese tramo concreto se mide en píxeles
escalados —mezclar sistemas de coordenadas sería peor—, así que **la unidad
puede cambiar a mitad de partido si la calibración llega tarde**. Quien muestre
la cifra debe decir cuál de las dos es: `report()` lo hace en
`meta.distance_unit`.

### `PossessionTracker` — posesión por equipo

```python
tracker = PossessionTracker(confirm_frames: int = 3)
tracker.update(candidate: str, dt: float) -> str          # portador confirmado
PossessionTracker.nearest_holder(players, ball_xy, threshold, use_world) -> (str, float)
tracker.share() -> {"team_1": float, "team_2": float}     # suma 100
tracker.percentages() -> {"team_1", "team_2", "none"}     # suma 100
tracker.snapshot() -> dict
tracker.to_state() / PossessionTracker.from_state(state)
```

| Garantía | Detalle |
|---|---|
| **Segundos, no frames** | `dt` son segundos reales; el reparto no depende de la velocidad de procesado |
| **Histéresis** | Un equipo necesita `confirm_frames` seguidos para que se le adjudique el balón |
| **`share()` suma 100** | Reparto entre equipos; ignora el tiempo sin dueño |
| **`percentages()` suma 100** | Reparto sobre el total, incluyendo `none` |
| **`changes` = cambios de manos** | El balón pasa a un equipo **distinto del último que lo tuvo**. `team_1 → none → team_1` **no** suma |
| **`interruptions` = disputas** | Veces que el balón quedó sin dueño |

`nearest_holder` devuelve `("none", inf)` si no hay balón, no hay jugadores, o
el más cercano supera `threshold`.

### `ExternalLoad` — carga externa del jugador

Lo que decide una sustitución no es la distancia total, sino cuánta fue a alta
intensidad, cuántas aceleraciones y frenadas hubo, y si eso está cayendo.

```python
carga = ExternalLoad(config: LoadConfig | None)
carga.add_step(*, t_start, dt_s, distance_m, speed_start_kmh, speed_end_kmh) -> None
carga.finalize() -> None
carga.summary() -> dict
carga.profile() -> list[dict]          # un bloque por minuto
carga.dropoff() -> dict | None
carga.relative_thresholds() -> dict
carga.to_state() / ExternalLoad.from_state(state, config)
```

**No se construye a mano en el bucle de frames.** `PlayerKinematics` la posee y
la alimenta con los tramos que ya validó, para que «tramo válido» tenga una sola
definición. Quien la instancie por su cuenta y le pase muestras crudas obtendrá
métricas que incluyen los saltos por cambio de identidad del tracker.

| Garantía | Detalle |
|---|---|
| **La tabla de bandas es única** | `kinematics.SPEED_ZONES` **es** `load.SPEED_BANDS`, el mismo objeto. Existieron como dos tablas con cortes distintos (7/14/20/25 y 7,2/14,4/19,8/25,2); fijado por `test_la_cinematica_y_la_carga_comparten_la_misma_tabla` |
| **Las bandas suman la distancia total** | Sin huecos ni solapes: los bordes se comprueban contra la propia tabla |
| **`speed_start_kmh=None` no es cero** | En el primer tramo de un jugador no hay velocidad previa. Tratarlo como cero fabricaba 25 m/s² en la primera observación de **cada** jugador |
| **Un esfuerzo tiene que sostenerse** | Por debajo de `min_effort_s` no cuenta; un sprint, además, necesita `min_sprint_m` |
| **`finalize()` cierra lo abierto** | Sin él se pierde el sprint con el que termina el partido |
| **La caída se normaliza por tiempo observado** | Un jugador tapado la mitad del tramo final no aparece como fundido. Fijado por `test_ver_menos_al_jugador_no_es_lo_mismo_que_verle_bajar` |
| **Memoria acotada** | `MAX_BUCKETS` bloques y `MAX_EFFORTS` esfuerzos con detalle; los contadores no se topan |

`summary()` devuelve, con estas unidades exactas:

```python
{
  "total_dist_m": float, "high_intensity_m": float, "sprint_dist_m": float,
  "bands_m": {str: float},          # claves = nombres de SPEED_BANDS
  "sprints": int, "accelerations": int, "decelerations": int,
  "high_intensity_efforts": int,    # sprints + aceleraciones + frenadas
  "max_accel_ms2": float, "max_decel_ms2": float,   # m/s², la frenada es negativa
  "peak_speed_kmh": float, "observed_s": float,
  "per_minute": {"dist_m", "high_intensity_m", "sprint_dist_m"},   # por minuto OBSERVADO
  "relative_thresholds_kmh": {"peak_kmh", "high_kmh", "sprint_kmh"},
  "dropoff": {"baseline_hi_m_per_min", "recent_hi_m_per_min",
              "change_pct", "window_s"} | None,
}
```

#### Los umbrales no son una constante de la naturaleza

Las bandas (14,4 / 19,8 / 25,2 km/h) son las de la bibliografía de GPS en
fútbol, y **cada fabricante corta donde quiere**. Quien compare estas cifras con
las de un GPS real tiene que mirar antes con qué bandas las cortó el GPS. Por
eso hay también umbrales **relativos** al pico de cada jugador (70 % y 90 %),
que es lo que la literatura reciente recomienda.

#### Lo que este módulo no puede arreglar

**Las aceleraciones son la métrica más sensible al ruido de todo el sistema:**
derivan una velocidad que ya es una derivada de una posición estimada. Un
tracker que tiembla dos píxeles produce aceleraciones inventadas. `min_effort_s`
es una defensa parcial, no una solución: **con tracking malo, el contador de
aceleraciones sube**. Quien muestre esa cifra debe mostrar al lado
`rejected_steps`, que es el indicador de calidad del tracking.

`dropoff()` devuelve `None` cuando no hay al menos una ventana completa de
referencia. **`None` no es cero:** cero afirmaría «no ha caído», y eso no
consta.

### `build_report` — el informe del partido

```python
build_report(
    players: Mapping[int, Mapping],      # {track_id: {"kinematics", "name", "team"}}
    possession: PossessionTracker,
    *, frames=0, duration_s=0.0, calibrated=False, config=None,
    include_positions=True, version="3.0", time_source="video",
) -> dict
```

Devuelve `meta`, `possession`, `teams`, `totals`, `leaderboards` y `players`.
`meta.time_source` y `meta.time_base_note` etiquetan la base de tiempo: unas
métricas de webcam (`"reloj"`) no son comparables con las de un vídeo, y
etiquetarlas es lo que impide compararlas sin saberlo.

`leaderboards` trae como mucho 10 entradas por categoría.

### Geometría

```python
find_homography(img_points, world_points) -> np.ndarray        # 3×3
perspective_transform_point(H, x, y) -> (float, float) | None
quad_is_degenerate(points) -> bool
validate_play_area(points) -> list[tuple[float, float]]        # >= 3 vértices
point_in_polygon(point, polygon) -> bool
```

`point_in_polygon` cuenta **el borde como dentro**: un jugador sobre la línea de
banda está en juego, y dejarlo fuera por un píxel sería peor que el falso
positivo que la zona viene a evitar. Con `polygon` vacío o `None` devuelve
`True` — sin zona definida, todo vale.

`validate_play_area` lanza `PlayAreaError` con menos de tres vértices o si el
polígono no encierra área: unos vértices alineados filtrarían absolutamente
todo.

`find_homography` exige cuatro puntos y lanza `CalibrationError` si el
cuadrilátero es degenerado. `perspective_transform_point` devuelve `None` si el
punto cae en el infinito proyectivo.

### Tablas de dominio

`SPEED_BANDS` (alias `SPEED_ZONES`), `HIGH_INTENSITY_KMH`, `SPRINT_KMH`,
`ACCEL_THRESHOLD_MS2`, `TIME_SOURCE_VIDEO`, `TIME_SOURCE_CLOCK`, `TIME_SOURCES`.
Son dato, no condicionales: quien añada una banda añade su columna en `bands_m`
sola. Los umbrales sueltos **tienen que coincidir con el borde de su banda**, y
eso lo comprueba una prueba: moverlos por separado dejaría el informe diciendo
que hay 200 m de alta intensidad y 0 m en la banda de alta velocidad.

## Errores

| Situación | Qué lanza | Qué debe hacer quien llama |
|---|---|---|
| `t` menor que el de la muestra anterior | `TimeBaseError` | **No capturar y seguir.** Es un error de programación en el productor de muestras: revisa de dónde sale el timestamp. Si el usuario hizo *seek* en el vídeo, ajusta el origen de tiempo antes de llamar |
| `t` igual al anterior | nada; suma en `duplicate_samples` | Nada. Si el contador crece mucho, el vídeo tiene marcas de tiempo rotas |
| Cuadrilátero de calibración degenerado | `CalibrationError` | Devolver 400 al usuario y pedir cuatro puntos que no sean colineales |
| `pixels_per_meter <= 0`, `smoothing` fuera de `[0,1]`, `speed_window_s <= 0` | `ValueError` en `KinematicsConfig` | Validar antes de construir; son errores de configuración |
| `confirm_frames < 1` | `ValueError` | Igual |

## Qué NO expone

- **`kin.samples` es la lista interna, no una copia.** Modificarla corrompe las
  métricas. Para leer, usa `trail()` o `summary()`.
- **`zone_distance_m` se devuelve por referencia en `to_state()`** — es
  `dict(...)`, copia superficial; no la mutes.
- **No hay garantía de orden** en las claves de `zones_m` más allá de que estén
  todas las de `SPEED_ZONES`.
- **`avg_speed_kmh` usa el tiempo *activo*, no el observado**: los tramos
  rechazados por salto imposible no cuentan como tiempo. Es distinto de
  `total_dist_m / observed_s` y a veces bastante distinto.
- **`max_speed_kmh` es la punta de la velocidad *suavizada*,** no del tramo
  crudo. Con `smoothing < 1` es sistemáticamente menor que la punta real.
- **No se garantiza estabilidad de `_last_team_holder`, `_candidate` ni
  `_sprint_elapsed`.** Son internos aunque `to_state()` serialice alguno.

## Quién depende de esto

| Carril | Qué usa |
|---|---|
| `PERCEPCION` | `Sample`, `PlayerKinematics.update`, `PossessionTracker.update` y `nearest_holder`; construye las muestras en `analyzer.py` |
| `API` | `build_report` para `/api/report` y `/api/export`; `to_state`/`from_state` para persistir la sesión |
| `CLIENTE` | Indirectamente: la forma de `summary()` y de `snapshot()` viaja en cada frame del stream |

## Cambios desde la versión anterior

### v2 (2026-08-19)

- **Rompe: los nombres y los cortes de las bandas cambian.** `carrera` y
  `alta_intensidad` pasan a ser `alta_velocidad` y `muy_alta_velocidad`, y los
  cortes pasan de 7/14/20/25 a 7,2/14,4/19,8/25,2 km/h, que son los de la
  bibliografía de GPS en fútbol. Quien tuviera un informe guardado con las
  claves viejas verá claves nuevas. `zones_m` sigue existiendo con ese nombre.
- **Rompe: `zone_distance_m` es ahora una propiedad de sólo lectura** que
  devuelve el diccionario de `load`. Antes era un acumulador propio; eran dos
  acumuladores del mismo recorrido y podían separarse en silencio.
- **Añade:** `ExternalLoad`, `LoadConfig`, `SquadLoad`, `band_for_speed`, y la
  clave `load` en `summary()` de cada jugador.
- **Añade:** en el informe, `totals.high_intensity_m`, `totals.accelerations`,
  `totals.decelerations` y tres rankings nuevos (`high_intensity`,
  `intensity_per_min`, `accelerations`).
- **Compatibilidad de estado:** una sesión guardada por v1 se restaura; se
  recuperan las bandas y el resto de la carga arranca a cero. Lo que no se midió
  entonces no se inventa.

### v1 (2026-08-18)

Primera publicación. Respecto del código previo a este contrato:

- **Rompe:** `changes` de `PossessionTracker` cambia de significado. Antes sumaba
  al adquirir el balón desde `none`; ahora sólo al cambiar de manos. Quien
  mostrara ese número verá cifras más bajas, y correctas.
- **Rompe:** `update()` ahora lanza `TimeBaseError` donde antes calculaba una
  distancia con `dt` negativo en silencio.
- **Añade:** `duplicate_samples`, `interruptions`, `meta.time_source`.
