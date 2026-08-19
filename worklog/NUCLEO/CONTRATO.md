# Contrato de NUCLEO

**Versión:** 1 · **Publicado:** 2026-08-18 · **Estable desde:** 2026-08-18

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

`SPEED_ZONES`, `TIME_SOURCE_VIDEO`, `TIME_SOURCE_CLOCK`, `TIME_SOURCES`. Son
dato, no condicionales: quien añada una zona añade su columna en `zones_m` sola.

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

Primera publicación. Respecto del código previo a este contrato:

- **Rompe:** `changes` de `PossessionTracker` cambia de significado. Antes sumaba
  al adquirir el balón desde `none`; ahora sólo al cambiar de manos. Quien
  mostrara ese número verá cifras más bajas, y correctas.
- **Rompe:** `update()` ahora lanza `TimeBaseError` donde antes calculaba una
  distancia con `dt` negativo en silencio.
- **Añade:** `duplicate_samples`, `interruptions`, `meta.time_source`.
