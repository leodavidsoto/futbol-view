# NUCLEO — estado

| | |
|---|---|
| **Estado** | LISTO_PARA_REVISION |
| **Último agente** | claude (turno 2 de NUCLEO) |
| **Última actualización** | 2026-08-19T20:10:00Z |
| **Contrato publicado** | sí — `worklog/NUCLEO/CONTRATO.md` **v2**. Rompe los nombres de las bandas; ver §Cambios |
| **Depende de** | nadie para empezar; `PLATAFORMA` para cerrar |
| **Requisitos asignados** | R-04, R-05, R-07, R-09, R-14, R-20, R-22 |

## Qué está hecho

Todo lo que trajo la PR #1, que arregló cuatro bugs reales de métrica:

- Distancia sin doble conteo, entre la muestra nueva y la inmediatamente anterior.
- Velocidad sobre tiempo real de vídeo, no sobre FPS de procesado.
- Posesión en segundos con un solo denominador, con histéresis.
- Rechazo de saltos por cambio de identidad del tracker, contabilizados aparte.

Y en este turno:

- **Guardia de la regla 5**: `update()` lanza `TimeBaseError` si el tiempo
  retrocede, y descarta —sin romper— una muestra con `t` repetido, contándola en
  `duplicate_samples`.
- **Prueba de invariancia al muestreo**, parametrizada sobre `frame_skip` 0, 2 y
  5, más la comparación directa de las tres frecuencias entre sí.
- **Robos separados de interrupciones** en `PossessionTracker` (ver decisión 2).
- **`meta.time_source`** viaja hasta el informe: unas métricas de webcam quedan
  etiquetadas y dejan de ser comparables con las de un vídeo por accidente.
- Contrato v1 publicado.

### Turno 2 — carga externa (`fcopilot/load.py`)

El informe medía distancia y velocidad, que es lo que se mide desde hace veinte
años. Lo que un preparador físico usa hoy para decidir un cambio no estaba:

- **Bandas con respaldo**: 7,2 / 14,4 / 19,8 / 25,2 km/h, las de la
  bibliografía de GPS en fútbol, en vez de los redondos 7/14/20/25 que había.
- **Aceleraciones y frenadas** por encima de ±3 m/s², que no existían en
  absoluto y son el mejor indicador de demanda metabólica y de riesgo de lesión.
- **Normalización por minuto observado**, sin la cual un suplente que entra diez
  minutos parece vago.
- **Umbrales relativos** al pico de cada jugador (70 % / 90 %), para no llamar
  paseo al esfuerzo máximo de un central lento.
- **Caída de rendimiento**: metros de alta intensidad por minuto de la última
  ventana contra los del resto del partido *del mismo jugador*. Es la métrica
  que responde «¿a quién cambio?», y es la que alimenta el semáforo del
  dashboard del DT.

Dos defectos encontrados escribiéndolo, ambos del tipo que produce datos
plausibles y falsos:

1. **La primera observación de cada jugador fabricaba una aceleración de
   25 m/s²** —el récord humano ronda 10— porque comparaba contra una velocidad
   inicial de cero que nadie había medido. `speed_start_kmh=None` significa
   ahora «no se sabe», que no es lo mismo que cero.
2. **Había dos tablas de bandas** con cortes distintos: la de `kinematics` y la
   de `load`. Ahora es un único objeto, y una prueba lo fija.

Comprobado por mutación: cinco mutaciones, cuatro caídas a la primera. La quinta
—quitar la normalización por tiempo observado en `dropoff`— **sobrevivió**,
porque la prueba original comparaba dos ventanas de igual duración, que es
justo el caso en el que da igual. Se añadió
`test_ver_menos_al_jugador_no_es_lo_mismo_que_verle_bajar`, que sí la caza.

## Qué falta

1. **Verificación cruzada** (`revisar-carril`) por un agente que no sea este.
2. El guardia de la regla 5 es sólido dentro de este carril, pero el agujero
   real está en `analyzer.py:261`, que cae al reloj de pared cuando falta el
   timestamp. Ese fichero es de `PERCEPCION`: solicitud abierta abajo.
3. **Ninguna de estas métricas está validada contra la realidad.** Las bandas,
   las aceleraciones y la caída hacen lo que dice el código y dan órdenes de
   magnitud plausibles, pero sin un partido etiquetado a mano no hay nada que
   diga si se parecen a lo que mediría un GPS puesto en el jugador. Sigue siendo
   el hueco de `ANALISIS.md` §0.7 y no lo cubre ningún carril.
4. `avg_speed_kmh` usa el tiempo activo y `max_speed_kmh` la velocidad suavizada.
   Las dos decisiones están documentadas en el contrato, pero ninguna está
   *probada* en sus extremos: un jugador con muchos saltos rechazados tiene una
   media que no se deduce de distancia/tiempo observado.

## Bloqueos activos

- ninguno.

## Decisiones

| # | Decisión | Por qué | Reversible | Qué la revierte |
|---|----------|---------|------------|-----------------|
| 1 | `fcopilot/__init__.py` es de este carril | Es la superficie pública del paquete y este carril está aguas arriba de todos | sí | Una línea de `carriles.json` |
| 2 | Un cambio de posesión **no** se obliga a pasar por `none`, pero pasar por `none` no cuenta como cambio | En un robo limpio el balón nunca está sin dueño, así que obligar a pasar por `none` inventaría interrupciones. Y un despeje recuperado por el mismo equipo no es un cambio de manos | sí | Volver a contar toda adquisición desde `none`; una condición en `update()` |
| 3 | `t` repetido descarta la muestra en vez de lanzar | Un vídeo real puede repetir marca de tiempo; eso es un defecto del material, no del llamador. Lanzar tumbaría el análisis entero por un frame | sí | Convertirlo en `TimeBaseError` también |
| 4 | `TimeBaseError` sólo salta hacia atrás, no detecta el reloj de pared | El reloj de pared **también** es monótono: ninguna comprobación local puede distinguirlo. Lo que sí se puede es etiquetar la fuente y propagarla al informe | no (es una limitación, no una elección) | Exigir la fuente en el propio `Sample`, lo que obligaría a tocar `PERCEPCION` |
| 5 | La carga la posee `PlayerKinematics` y se alimenta desde `update()` | Si la carga recorriera las muestras por su cuenta, las dos podrían discrepar sobre qué tramo es válido, y discreparían en silencio | sí | Hacer que `ExternalLoad` acepte muestras y no tramos |
| 6 | Las bandas cambian de nombre y de corte, rompiendo el contrato v1 | Mantener las dos tablas era el defecto; mantener sólo la vieja habría dejado el informe con cortes que no coinciden con ningún GPS del mercado | sí, con coste | Volver a `SPEED_ZONES` propio en `kinematics.py` |

## Solicitudes a otros carriles

| Carril | Qué necesito | Desde |
|---|---|---|
| `PERCEPCION` | `analyzer.py:261` usa `time.monotonic()` cuando falta el timestamp, así que un análisis puede producir métricas de reloj sin que nadie se entere. Que declare la fuente de tiempo y la propague a `build_report(time_source=...)` | 2026-08-18 |

## Notas para quien retome

- **Trampa que ya está en el código:** `_distance_m` mide en píxeles cuando una
  muestra tiene coordenadas de mundo y la otra no. Es lo correcto —mezclar
  sistemas de coordenadas sería peor— pero significa que la distancia de un
  jugador cambia de unidad a mitad de partido si la calibración llega tarde. Si
  lo tocas, dilo en el contrato.
- `_compute_speed` cae hacia atrás a la velocidad anterior cuando la crudo supera
  `max_speed_kmh`. Es un suavizado deliberado, no un descuido: sin él, un salto
  rechazado por distancia seguía colándose en la velocidad.
- La cobertura de este carril ya era alta antes de este turno (kinematics 99 %,
  possession 99 %, report 100 %) y aun así **probaba corrección, no
  invariancia**. Esa es la distinción que dejó pasar el bug original, y por eso
  la prueba nueva va parametrizada sobre tres frecuencias.
- **Comprobado por mutación**, no por confianza: reintroduciendo el doble conteo
  caen 6 pruebas, y reintroduciendo la velocidad sobre FPS de procesado caen 6.
  Detalle importante: con el bug de FPS, `test_la_velocidad_no_depende_del_muestreo[0]`
  **pasa** —a `frame_skip` 0 los FPS falsos coinciden con los reales— y sólo
  fallan `[2]` y `[5]`. Es exactamente por eso que la prueba va parametrizada: la
  versión con un solo valor de `frame_skip` no habría cazado nada.
- Dos pruebas previas afirmaban la semántica vieja de `changes` y se
  actualizaron: `test_un_frame_suelto_del_rival_no_roba_la_posesion` (ahora
  espera 0 cambios, que es lo correcto: el balón nunca cambió de manos) y
  `test_snapshot_y_serializacion` (el conjunto de claves creció). Lo que
  comprobaban de verdad —que un frame suelto del rival no roba— sigue
  comprobándose igual.
- `from_state` reconstruye `_last_team_holder` del portador guardado cuando el
  campo no está. Es correcto salvo que el balón estuviera en disputa justo al
  guardar, en cuyo caso el primer equipo que lo recupere contará como cambio de
  manos sin serlo. Un error de un evento en una sesión restaurada; no me pareció
  que justificara versionar el estado.
