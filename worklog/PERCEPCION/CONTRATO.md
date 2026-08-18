# Contrato de PERCEPCION

**Versión:** 1 · **Publicado:** 2026-08-18 · **Estable desde:** 2026-08-18

Consume el contrato de `NUCLEO` v1. Convierte píxeles en jugadores con identidad
y equipo, y alimenta los objetos cinemáticos con muestras que llevan tiempo de
vídeo.

## Qué expone

### `Detector` — detección de personas y balón

```python
Detector(config: dict)                       # lee model_path, confidence, iou, imgsz,
                                             # augment, agnostic_nms, detection_mode,
                                             # sahi_slice, sahi_overlap
detector.predict(frame: np.ndarray) -> DetectionResult
detector.reload(model_path: str) -> None
detector.sahi_ready -> bool
```

```python
DetectionResult = tuple[
    list[np.ndarray],              # cajas de personas, xyxy en float
    list[float],                   # confianzas, mismo orden que las cajas
    list[tuple[np.ndarray, float]] # candidatos a balón: (xyxy, confianza)
]
```

| Garantía | Detalle |
|---|---|
| **Las dos listas de personas van alineadas** | `person_xyxy[i]` corresponde a `person_conf[i]` |
| **Sólo persona y balón** | Cualquier otra clase COCO se descarta en `split_by_class` |
| **Degradación de SAHI** | Con `detection_mode="sahi"` y SAHI no disponible, `predict` cae al camino normal y **sigue detectando**. No devuelve vacío |
| **Modelo compartido** | Dos `Detector` con la misma ruta comparten el objeto YOLO: cargarlo dos veces duplicaría la memoria |
| **Sin detecciones no es error** | Un frame vacío devuelve `([], [], [])` |

### `shared_yolo_registry` / `shared_osnet_registry`

```python
registry.get(path) -> modelo        # carga perezosa y compartida
registry.register(path, modelo)     # inyección; es lo que usan los tests
registry.clear() -> None
registry.stats() -> dict
```

`shared_yolo_registry.get` lanza `DetectorUnavailable` si `ultralytics` no está.
`shared_osnet_registry.get` devuelve `None` si `torch` no está — **no lanza**:
OSNet es opcional dentro de lo opcional, y quedarse sin él degrada a KMeans en
vez de tumbar el análisis.

### Trackers

Los tres cumplen la misma forma:

```python
tracker.update(boxes, confs) -> list[tuple[int, float, float, float, float]]
#                                     track_id, x1, y1, x2, y2
```

`resolve_tracker_type(requested) -> str` devuelve el tracker que **se va a usar
de verdad**: si el pedido no está disponible, degrada. El valor efectivo viaja en
`stats.tracker` de cada frame, así que quien mire el resultado sabe cuál corrió.

| Garantía | Detalle |
|---|---|
| **Un track nuevo tarda un frame en confirmarse** | El primer frame de un track no aparece en la salida. Es el calentamiento del tracker, no una pérdida |
| **Identidades estables en un cruce** | Dos jugadores que se superponen y se separan conservan su identidad. Fijado por `test_las_identidades_no_se_intercambian_al_superponerse` |

### Clasificadores de equipo

```python
clf.fit(frame, bboxes) -> None
clf.predict(frame, bbox, track_id=None) -> "team_1" | "team_2" | "unknown"
clf.is_fitted -> bool
clf.name -> "kmeans" | "grass_kmeans" | "osnet"
```

| Garantía | Detalle |
|---|---|
| **Etiquetas deterministas** | Los centroides se ordenan por tono y valor: dos ajustes seguidos sobre los mismos datos dan las mismas etiquetas. Sin esto, cada reajuste podía intercambiar `team_1` y `team_2` |
| **Voto por track** | La etiqueta sale de una ventana de votos, no del último frame: una sombra que tiñe la camiseta un frame no cambia de equipo al jugador |
| **Un solo kit no se parte en dos** | Si los dos centroides están a menos de `min_separation`, no se ajusta y se sigue acumulando muestras |
| **Ventana acotada** | Como mucho `vote_window` votos por track |
| **`unknown` es un valor legítimo** | Antes de tener muestras suficientes, y para un track sin votos |

### `FootballAnalyzer` — el bucle de frames

```python
analyzer.process_frame(frame, timestamp: float | None = None) -> dict
analyzer.get_export(include_positions=True) -> dict      # delega en build_report
analyzer.time_source -> "video" | "reloj" | None
```

**La base de tiempo es la garantía principal de este carril.** `timestamp` son
segundos de vídeo; si falta se usa el reloj de la cámara, que es legítimo sólo
en directo. La fuente:

1. se fija con la primera llamada y **no puede cambiar**: mezclarlas lanza
   `TimeBaseError`;
2. viaja en `stats.time_source` de cada frame;
3. llega hasta `meta.time_source` del informe.

Ninguna comprobación local puede distinguir el reloj de pared del tiempo de
vídeo —los dos son monótonos y crecen igual—, así que declarar la fuente y
propagarla es la única defensa real. Reiniciar la sesión (`reset()`) la libera.

Forma de la respuesta de `process_frame`:

```python
{
  "frame": int, "t": float, "fps": float,           # fps = de PROCESADO, no de vídeo
  "players": [{"track_id", "name", "team", "bbox", "center",
               "speed_kmh", "total_dist_m", "trail", ...}],
  "ball": {...} | None,
  "stats": {"total_players", "team_1_count", "team_2_count", "classifier_ready",
            "tracker", "calibrated", "elapsed_s", "time_source"},
  "timings_ms": {"detect", "track", "classify", "ball", "total"},
  "possession": {...},                               # snapshot de NUCLEO
}
```

## Errores

| Situación | Qué lanza | Qué debe hacer quien llama |
|---|---|---|
| `ultralytics` no instalado y se construye un `Detector` | `DetectorUnavailable` | Devolver 503 con el mensaje: dice el comando de instalación |
| `ultralytics` no instalado y se llama a `predict` | `DetectorUnavailable` | En streaming, emitir la línea `{"error": ...}` y cerrar |
| Se mezcla tiempo de vídeo con reloj en el mismo análisis | `TimeBaseError` | **No capturar y seguir.** Reiniciar la sesión antes de cambiar de fuente |
| El tiempo retrocede dentro de la misma fuente | nada: el analizador lo aplana | Nada. Es un *seek* del usuario y se ignora el salto |
| `torch` no instalado y se pide OSNet | nada: `available` es `False` | Degradar a `grass_kmeans` y decírselo al usuario |

## Qué NO expone

- **`fps` del resultado son frames de procesado por segundo**, es decir, lo
  rápido que va la máquina. **No es el fps del vídeo** y no debe usarse para
  ninguna métrica. Está ahí para la barra de progreso.
- **`analyzer.tracks` es el diccionario interno.** Mutarlo corrompe las métricas.
- **El `track_id` no es estable entre sesiones** ni sobrevive a un `reset()`.
  Sólo tiene sentido dentro de un análisis.
- **`stats.tracker` puede no ser el tracker que se pidió**: si el pedido no está
  disponible, degrada, y este campo dice cuál corrió de verdad.
- **No se garantiza el orden de `players`** dentro de un frame.
- **La red OSNet en sí no está probada.** Lo que se prueba es la lógica que la
  rodea, con embeddings sintéticos. Las líneas 44-180 de `osnet.py` sólo se
  ejecutan con `torch` instalado, que en CI no está por diseño.

## Quién depende de esto

| Carril | Qué usa |
|---|---|
| `API` | `FootballAnalyzer` entero, `DetectorUnavailable` para traducir a HTTP, las banderas `*_AVAILABLE` para `/api/config`, y `time_source` para etiquetar el informe |
| `CLIENTE` | Indirectamente: la forma de `process_frame` es cada línea del stream NDJSON |

## Cambios desde la versión anterior

Primera publicación. Respecto del código previo:

- **Añade:** `analyzer.time_source`, `stats.time_source`, y `TimeBaseError` al
  mezclar fuentes. Antes, un análisis sin `timestamp` producía métricas de reloj
  de pared sin que nada lo indicara — el mismo agujero que ya multiplicó las
  velocidades por tres una vez.
- **Rompe:** llamar a `process_frame` sin `timestamp` después de haberlo llamado
  con él (o al revés) ahora lanza donde antes mezclaba en silencio.
