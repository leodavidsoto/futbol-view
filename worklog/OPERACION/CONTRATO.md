# Contrato de OPERACION

**Versión:** 1 · **Publicado:** 2026-08-19

Consume `API` v1 (tabla de variables de entorno y puertos). Es una hoja: nadie
depende de este contrato dentro del sistema, pero sí quien despliega.

## Qué expone

### Imagen

`Dockerfile` con tres etapas y **dos targets**:

| Target | Qué es | Puerto |
|---|---|---|
| `servicio` | La API con sus dependencias pesadas | 8000 |
| `web` | nginx sirviendo el cliente compilado y haciendo de proxy | 80 |

Van separados porque **el backend no monta estáticos**: ese fichero pertenece a
`API` y montarlos desde aquí sería tocar un carril ajeno. Hay solicitud abierta.
nginx delante es la separación correcta de todas formas, y hace que cliente y API
compartan origen, con lo que CORS puede cerrarse.

Garantías de la imagen:

- **Los pesos no van dentro.** Se montan como volumen de sólo lectura.
- **Corre como usuario sin privilegios** (uid 10001): el proceso decodifica
  vídeo de fuera con librerías nativas, que es donde menos conviene ser root.
- **PyTorch en CPU** por defecto (`ARG TORCH_INDEX`). Con GPU, quítalo.
- `libgl1` y `libglib2.0-0` instalados: sin ellos `import cv2` falla en tiempo
  de ejecución con un error que no menciona el paquete que falta.
- `HEALTHCHECK` contra `/health`, que responde sin credencial a propósito.

### `docker compose`

```bash
python3 scripts/fetch_weights.py --dest ./weights
docker compose up --build                        # cliente en :8080
docker compose --profile mantenimiento up -d purga
```

La API **no publica puertos**: sólo se llega por nginx. Es lo que mantiene el
mismo origen; para depurar, añade `8000:8000`.

### `scripts/fetch_weights.py`

```
--dest DIR        directorio de pesos (MODEL_ROOT)
--check-only      no descarga; sólo comprueba
--print-hashes    imprime los hashes de lo que haya
```

| Garantía | Detalle |
|---|---|
| **Descarga atómica** | A un `.parcial` que se renombra al terminar: nunca deja un fichero a medias en su sitio |
| **Verificación de integridad** | SHA-256 contra `scripts/weights.sha256.json`. Un `.pt` es un pickle y cargarlo ejecuta código |
| **Idempotente** | Lo que ya está no se vuelve a descargar |
| **Los `TODO(config)` no cuentan como hash** | Si contaran, se compararía el hash real contra el texto del TODO |
| **Salida 1 si falta algo obligatorio** | Y el mensaje dice el comando exacto |

### `scripts/purge_sessions.py`

```
--dir DIR             SESSION_STATE_DIR
--max-age-days N      retención; por defecto 7
--dry-run             dice qué borraría
--loop SEGUNDOS       repite en vez de salir
```

| Garantía | Detalle |
|---|---|
| **Sólo toca `*.json.gz`** | Corre desatendido: un glob ancho sobre un directorio mal configurado borraría lo que no es suyo |
| **`--max-age-days 0` es un error, no «borra todo»** | Cero incluiría la sesión en curso |
| **El vídeo no se toca** | Ya se borra al terminar el análisis; aquí sólo van datos derivados |
| **Devuelve ficheros y bytes** | Para poder vigilarlo desde fuera |

## Errores

| Situación | Qué pasa | Qué hacer |
|---|---|---|
| Faltan pesos obligatorios | salida 1 con el comando | Ejecutar `fetch_weights.py` |
| El hash no coincide | salida 1, **no se usa el fichero** | Borrarlo y volver a descargarlo de una fuente fiable |
| Sin URL fijada (OSNet) | aviso, no bloquea | Colocarlo a mano; sin él se degrada a `grass_kmeans` |
| `--max-age-days` ≤ 0 | salida 2 | Poner un valor positivo |
| Descarga cortada | salida 1, sin fichero parcial | Reintentar |

## Qué NO expone

- **La imagen no está construida ni probada en este entorno**: no hay demonio de
  Docker disponible aquí. El `Dockerfile` y el `compose` están escritos y
  revisados, pero **nadie los ha ejecutado todavía**. Es lo primero que hay que
  hacer antes de fiarse de ellos.
- **No hay hashes reales** en `weights.sha256.json`: sólo `TODO(config)`. Nadie
  puede fijar un hash que no ha calculado, y la regla 2 prohíbe inventarlo.
- **No hay despliegue con GPU probado**, ni fichero de CUDA.
- **No hay copias de seguridad** de `SESSION_STATE_DIR`, sólo purga.
- **No hay vídeo de prueba** en el repositorio, así que el recorrido de extremo a
  extremo no se puede automatizar.

## Quién depende de esto

Nadie dentro del sistema. Fuera: quien despliegue, y `INSTALACION_V2.md`
secciones 0, 9, 10, 11 y 12.
