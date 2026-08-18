# AGENTS.md — el contrato de trabajo

Lo primero que lee cualquier agente que entra a este repositorio. Si sólo vas a
leer un documento, que sea este; después ve a `CARRILES.md` por tu carril.

## Qué construimos

Football Copilot convierte la grabación de un partido de fútbol amateur en
métricas de rendimiento por jugador y por equipo —distancia, velocidad punta,
sprints, zonas de esfuerzo, posesión— en vivo mientras el vídeo se procesa, sin
cámaras especiales ni chalecos GPS.

| Pieza | Elección | Quién la decidió |
|---|---|---|
| Lenguaje del núcleo | Python 3.11 | venía dado |
| API | FastAPI + uvicorn, streaming NDJSON | venía dado |
| Detección | YOLOv11 (`ultralytics`), opcionalmente troceado con SAHI | venía dado |
| Tracking | Norfair por defecto; ByteTrack y un tracker de centroides propio como alternativas | venía dado |
| Clasificación de equipos | KMeans sobre color de camiseta, con variante consciente del césped; OSNet con `torch` como opción | venía dado |
| Cliente | React 18 + Vite | venía dado |
| Pruebas | pytest + vitest, con detector guionizado | venía dado (PR #1) |
| Dependencias pesadas | **opcionales**: el servicio arranca sin ellas | venía dado, y es una restricción, no una comodidad |
| Fuente de verdad del corte | `carriles.json`, renderizado en `CARRILES.md` | decidido en el intake (D-03) |

Proponer una alternativa a cualquiera de estas filas **requiere abrir un ADR**,
no un mensaje de worklog. Cambiar de tracker o de framework a mitad de carril no
es una decisión de carril.

## Reglas innegociables

Cada regla lleva su guardia al lado. Donde el guardia dice «por construir», la
regla es hoy una convención y ese es precisamente el trabajo del carril
responsable.

1. **Contrato antes que código.** Ningún carril se implementa hasta que su
   contrato esté publicado en `worklog/<CARRIL>/CONTRATO.md`. Los demás programan
   contra el contrato, nunca contra la implementación. *Guardia:* el skill
   `tomar-carril` se detiene si falta el contrato de una dependencia.

2. **No inventes credenciales ni datos de proveedor.** Si falta un token, una URL
   o un fichero de pesos, deja un `TODO(config)` explícito y regístralo como
   bloqueo en tu `STATE.md`. No pongas valores de ejemplo que parezcan reales.
   En este repositorio importa especialmente con los pesos del modelo: `yolo11x.pt`
   y `osnet_x1_0_imagenet.pth` no están y nadie los provisiona (R-26, R-29).

3. **Un agente = un carril por turno.** No toques ficheros de un carril que no te
   fue asignado. Si necesitas un cambio ahí, anótalo como solicitud en el
   `STATE.md` de *ese* carril y sigue con lo tuyo. *Guardia:*
   `python3 tools/check_carriles.py --diff <base> --carril <TU_CARRIL>`, que corre
   en CI.

4. **Las correcciones no borran historia.** `worklog/EVENTS.jsonl` es de sólo
   añadir: un error se corrige con una línea compensatoria que referencia la
   anterior, nunca editando ni borrando. *Guardia:* el checker rechaza cualquier
   diff que elimine líneas de ese fichero.

5. **El tiempo de vídeo es la base de toda métrica.** Ninguna métrica se calcula
   con FPS de procesado, con el reloj de pared ni con el número de frame. Esta
   regla existe porque su violación ya produjo velocidades multiplicadas por tres
   y nadie lo notó hasta que alguien leyó el código. *Guardia:* parcial —
   `Sample` exige `t`; falta que `PlayerKinematics.update` rechace un `t` no
   monótono (trabajo de `NUCLEO`).

6. **La sesión es la frontera de aislamiento.** Ninguna ruta nueva accede al
   estado de una sesión sin pasar por la dependencia de sesión. *Guardia:* por
   construir — es el criterio de cierre de `API`. Mientras no exista, esta regla
   es lo único que separa los datos de dos usuarios.

7. **Las dependencias pesadas se importan de forma opcional.** Un `import
   torch`, `import ultralytics` o `import sahi` en el cuerpo de un módulo rompe
   la propiedad de que el servicio arranque en un entorno ligero. Van dentro de
   un `try/except ImportError` con su bandera `*_AVAILABLE`. *Guardia:* CI corre
   en un entorno que no las tiene, así que un import obligatorio rompe el build
   solo.

## Cómo registrar el trabajo

Una línea JSON por evento, **añadida** al final de `worklog/EVENTS.jsonl`. Nunca
más de una línea por turno.

```
{"ts":"2026-08-18T22:40:00Z","carril":"NUCLEO","agente":"claude-1","evento":"abre","estado":"EN_CURSO","resumen":"Toma NUCLEO para el guardia de monotonía temporal","refs":["R-14"],"bloqueos":[]}
```

| Campo | Qué va |
|---|---|
| `ts` | ISO-8601 en UTC con `Z` |
| `carril` | ID exacto de `carriles.json` |
| `agente` | quién eres, para poder preguntarte |
| `evento` | `abre`, `avanza`, `publica_contrato`, `entrega`, `revisa`, `bloquea`, `corrige` |
| `estado` | el estado del carril **al terminar** el turno |
| `resumen` | una frase; el diff cuenta el resto |
| `refs` | IDs de requisito, de ambigüedad o de commit |
| `bloqueos` | lista; **no vacía obligatoriamente** si `estado` es `BLOQUEADO` |

Un evento `corrige` lleva en `refs` el `ts` del evento que corrige. Así se
deshace sin borrar.

## Estados válidos

```
NO_INICIADO ──► EN_CURSO ──► LISTO_PARA_REVISION ──► HECHO
                    │                  │
                    └──────► BLOQUEADO ◄┘
                             (exige bloqueos no vacío)
```

De `BLOQUEADO` sólo se sale a `EN_CURSO`. Nada salta de `EN_CURSO` a `HECHO`: la
revisión la hace otro agente, y eso es a propósito.

## Definición de «Hecho»

Un carril es `HECHO` cuando **todas** estas casillas están marcadas por alguien
que no lo implementó:

- [ ] `CONTRATO.md` publicado, y describe lo que el código hace de verdad.
- [ ] Los requisitos que `carriles.json` le asigna están implementados, uno por uno.
- [ ] El criterio de cierre de su ficha en `CARRILES.md` lo demuestra una prueba
      que existe y pasa.
- [ ] `python3 tools/check_carriles.py --diff origin/main --carril <ID>` sale con 0.
- [ ] La suite completa pasa: `pytest` y, si tocó `frontend/`, `npm test` y `npm run lint`.
- [ ] `STATE.md` tiene la tabla de decisiones con su columna de reversibilidad y
      las notas para quien retome.
- [ ] Ninguna regla innegociable quedó violada — se comprueban una a una, no de
      un vistazo.

## Qué hacer ante una ambigüedad

La regla de las puertas, y se aplica igual para todos:

- **Una puerta** — equivocarse cuesta rehacer trabajo hecho, migrar datos
  escritos o romper algo publicado. **Pregunta y detente.** Regístrala como
  bloqueo.
- **Dos puertas** — equivocarse cuesta un rato. **Decide, anótala en la tabla de
  decisiones de tu `STATE.md` con qué la revertiría, y sigue.**

Al clasificar, mira el momento: una decisión de dos puertas hoy puede tener una
sola dentro de tres carriles, cuando ya haya código encima. Si crees que es el
caso, dilo en la fila.

Las ambigüedades de una puerta que ya están abiertas y esperan respuesta humana
están en `ANALISIS.md` §0.5 (A-01 a A-05). Antes de abrir una nueva, comprueba
que no sea una de esas.

## Por dónde se empieza

1. `ANALISIS.md` — qué es esto y qué se sabe.
2. `CARRILES.md` — tu carril, tus rutas, tu criterio de cierre.
3. `worklog/EVENTS.jsonl` — completo, no las últimas líneas: el orden importa.
4. `worklog/<TU_CARRIL>/STATE.md` — dónde lo dejó el anterior.

Y usa los skills: `tomar-carril` para abrir, `cerrar-turno` para cerrar. El
segundo es obligatorio.
