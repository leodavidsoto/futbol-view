# CARRILES.md — el mapa

Descomposición de Football Copilot en unidades asignables a **un** agente por
turno. Sale de `ANALISIS.md`; no se lee sin haberlo leído antes.

> **Fuente de verdad:** `carriles.json`. Este documento lo renderiza en prosa.
> Cambiar uno sin el otro hace fallar `tools/check_carriles.py`, y eso es
> deliberado: añadir un carril son dos pasos, y omitir el segundo tiene que
> romper en el acto en vez de dejar un carril invisible.

## El criterio de corte

Se cortó por **razón de cambio y propiedad del dato**, no por capa técnica.

Un corte en «backend / frontend / modelo» habría producido tres carriles que se
bloquean entre sí: cada funcionalidad los toca todos y ninguno cierra hasta que
cierran los tres. El corte que hay abajo produce carriles que cierran solos
porque cada uno es dueño de una pregunta distinta: *qué significa una métrica*
(NUCLEO), *cómo se convierten píxeles en jugadores* (PERCEPCION), *quién puede
pedir qué* (API), *qué ve la persona* (CLIENTE), *dónde corre esto* (OPERACION)
y *cómo se hacen cumplir las reglas* (PLATAFORMA).

`PLATAFORMA` es infraestructura de verdad según la prueba de la Fase 1: su
contrato lo consumen todos los demás y ella no consume el de nadie.

## Responsabilidad, no exclusividad

La matriz de trazabilidad asigna cada requisito a **un carril responsable**. Eso
no significa que ningún otro carril escriba código relacionado: R-07 (calibrar
el campo) es de `NUCLEO` porque la homografía es la sustancia, y `API` expone la
ruta que la recibe. La regla operativa es la de propiedad de ficheros, que sí es
exclusiva y sí la comprueba el guardia. La trazabilidad responde a otra
pregunta: *¿a quién le pido cuentas si esto no funciona?*

---

## Los carriles

### PLATAFORMA · Gobierno ejecutable

**Objetivo.** Que las reglas de este repositorio las haga cumplir un comando, no
la buena voluntad de quien tenga prisa.

**Depende de:** nadie. Es la ola 1.

**Contrato que publica.** El esquema de `carriles.json`, la interfaz de línea de
comandos de `tools/check_carriles.py` (códigos de salida incluidos), y el
formato de línea de `EVENTS.jsonl`.

**Rutas propias.** `carriles.json`, `tools/**`, `tests/test_gobernanza.py`,
`tests/conftest.py`, `pytest.ini`, `requirements-dev.txt`, `.github/**`,
`.claude/**`, los cuatro documentos de gobierno, `README.md`, `TESTING.md`,
`.gitignore`, `worklog/README.md`, `worklog/PLATAFORMA/**`.

**Requisitos:** R-18, R-23.

**Criterio de cierre.** `python3 tools/check_carriles.py` sale con 0 en un
repositorio sano y con 1 ante cada uno de estos seis casos, cada uno con su
prueba en `tests/test_gobernanza.py`: dos carriles reclaman el mismo fichero; un
fichero versionado no lo reclama nadie; hay un ciclo de dependencias; un carril
está en el manifiesto y no en el documento; falta un `STATE.md`; un requisito
del catálogo no lo cubre nadie. Y el guardia corre en CI sobre el diff de cada
rama.

**Trabajo pendiente detectado.** El guardia existe desde este turno; falta
cablearlo en CI sobre el diff (`--diff origin/main --carril <ID>`) y falta el
suelo de cobertura, hoy inexistente: la suite pasa igual si alguien borra un
módulo entero de tests.

---

### NUCLEO · Qué significa una métrica

**Objetivo.** Ser la única definición de qué significa una métrica de partido, y
que esa definición sea comprobable sin vídeo, sin modelo y sin servidor.

**Depende de:** nadie para empezar. De `PLATAFORMA` para cerrar.

**Contrato que publica.** `Sample`, `PlayerKinematics` (`update`, `summary`),
`PossessionTracker` (`share`, `percentages`, `snapshot`), `build_report`, y las
funciones de homografía. Es el contrato que consumen `PERCEPCION` y `API`, así
que es el primero que hay que publicar.

**Rutas propias.** `fcopilot/__init__.py`, `fcopilot/py.typed`,
`fcopilot/kinematics.py`, `possession.py`, `report.py`, `geometry.py` y sus
cuatro ficheros de test.

**Requisitos:** R-04, R-05, R-07, R-09, R-14, R-20, R-22.

**Criterio de cierre.** Una prueba demuestra que analizar el mismo movimiento
con `frame_skip` 0, 2 y 5 da la misma distancia y la misma velocidad dentro de
un margen declarado. Es la prueba que habría cazado el bug que la PR #1 arregló,
y no existe: hoy se prueba que el cálculo es correcto, no que sea **invariante
al muestreo**, que es la propiedad que de verdad se rompió.

**Trabajo pendiente detectado.** El guardia de R-14 está a medias: `Sample`
exige `t`, pero nada impide que ese `t` venga del reloj de pared en vez del
tiempo de vídeo. Falta que `PlayerKinematics.update` rechace muestras cuyo `t`
no avance de forma monótona. Y falta responder la pregunta abierta de la
máquina de estados de posesión (§0.6 de `ANALISIS.md`): si un cambio de portador
debe pasar siempre por `none`, hoy `changes` mezcla robos con pérdidas.

---

### PERCEPCION · De píxeles a jugadores

**Objetivo.** Convertir píxeles en jugadores con identidad y equipo estables, y
degradarse con dignidad cuando falten las dependencias pesadas.

**Depende de:** `NUCLEO` (consume `Sample` y alimenta los objetos cinemáticos).

**Contrato que publica.** `DetectionResult`, la interfaz de tracker
(`update(boxes, confs) -> [(track_id, x, y, w, h)]`), la de clasificador de
equipo, `DetectorUnavailable` y las banderas `*_AVAILABLE`.

**Rutas propias.** `fcopilot/detection.py`, `tracking.py`, `teams.py`,
`osnet.py`, `analyzer.py` y sus tests.

**Requisitos:** R-01, R-02, R-03, R-16.

**Criterio de cierre.** Con el detector guionizado, una secuencia sintética en
la que dos jugadores se cruzan produce dos tracks estables y ninguna
reasignación de equipo; y el camino degradado —sin `ultralytics`, sin `torch`—
devuelve `DetectorUnavailable` en la llamada y no en el import, con prueba que
lo fija.

**Trabajo pendiente detectado.** `fcopilot/osnet.py` está al 15 % de cobertura y
`detection.py` al 75 %: el camino con `torch` no se ejercita en absoluto, así que
la degradación está probada y el funcionamiento normal no. La ventana de votos
del clasificador de equipos no tiene prueba en sus extremos.

---

### API · Quién puede pedir qué

**Objetivo.** Exponer el análisis por HTTP con una frontera de confianza que hoy
no existe: aislar sesiones de verdad, no por convención.

**Depende de:** `NUCLEO` (forma del informe) y `PERCEPCION` (analizador).

**Contrato que publica.** La tabla de rutas con sus esquemas de entrada y
salida, la tabla de errores con qué debe hacer quien llama ante cada código, el
protocolo NDJSON de `/api/process-video` —incluida la línea de error a mitad de
stream, que hoy no está documentada en ningún sitio— y el contrato de
`session_id`.

**Rutas propias.** `football_copilot_v2_backend.py`, `fcopilot/sessions.py`,
`fcopilot/config.py` y sus tests.

**Requisitos:** R-08, R-10, R-13, R-15, R-17, R-19, R-21, R-24, R-25, R-27, R-28.

**Criterio de cierre.** Un test recorre todas las rutas registradas en la
aplicación FastAPI y falla si alguna no declara la dependencia de sesión: es el
guardia de R-15, y hace imposible añadir una ruta que se salte el aislamiento en
vez de recordar que no hay que hacerlo. Más: una petición con el `session_id` de
otra sesión no devuelve datos ajenos, con prueba.

**Trabajo pendiente detectado.** No hay **ninguna** autenticación (R-27) y
`CORS_ALLOW_ORIGINS` es `*` por defecto: el `session_id` lo elige el cliente, así
que cualquiera que sepa o adivine uno lee el partido de otro. Con A-01 sin
responder, esto es aceptable en local e inaceptable expuesto. El límite de
subida es 1 GB por petición y no hay tope acumulado ni por cliente (R-28).

**Riesgo declarado.** Es el carril más cargado: once requisitos y la ruta
crítica pasa por él. Si no cierra en un turno, el plan de partición está
decidido de antemano: `fcopilot/sessions.py` y su test salen a un carril propio
`SESIONES`, que tiene contrato distinto (ciclo de vida y persistencia) y rutas
disjuntas. No se parte de otra forma.

---

### CLIENTE · Lo que ve la persona

**Objetivo.** Que la mitad que no se refactorizó deje de ser un fichero de 1915
líneas con cuarenta `useState`, y que se pueda probar.

**Depende de:** `API`.

**Contrato que publica.** Ninguno hacia dentro del sistema: es una hoja del
grafo. Publica igualmente su `CONTRATO.md` declarando qué partes del contrato de
`API` consume, para que `API` sepa qué no puede romper sin avisar.

**Rutas propias.** `frontend/**`, `worklog/CLIENTE/**`.

**Requisitos:** R-06, R-11, R-12.

**Criterio de cierre.** `App.jsx` baja de 400 líneas y la lógica extraída tiene
pruebas de componente, no sólo de las funciones puras de `src/lib/`. Hoy hay 65
pruebas y ninguna toca un componente.

**Trabajo pendiente detectado.** El backend se partió en un paquete testeable y
el cliente sigue siendo el monolito equivalente: 1915 líneas, ~40 `useState` en
un solo componente. Es el mismo problema que la PR #1 resolvió en el otro lado.

**Nota sobre el tamaño.** Tres requisitos es el recuento más bajo del mapa y el
trabajo es de los mayores. La cuenta de requisitos mide responsabilidad, no
esfuerzo; no la uses para dimensionar.

---

### OPERACION · Dónde corre esto

**Objetivo.** Que alguien que no escribió esto pueda levantarlo, con los pesos
correctos, y sepa qué hacer cuando se rompa.

**Depende de:** `API` (necesita la lista de variables de entorno y puertos).

**Contrato que publica.** La tabla de variables de entorno con sus valores por
defecto y cuáles son obligatorias en producción; el procedimiento de provisión
de pesos con su verificación; y el runbook de los fallos conocidos.

**Rutas propias.** `Dockerfile`, `docker-compose.yml`, `.dockerignore`,
`deploy/**`, `scripts/**`, `requirements_v2.txt`, `INSTALACION_V2.md`,
`QUICK_START.md`.

**Requisitos:** R-26, R-29, R-30.

**Criterio de cierre.** Desde un clon limpio y sin nada instalado, un comando
documentado levanta el sistema y analiza un vídeo de prueba de extremo a
extremo. Hoy eso no se puede hacer: los pesos se dan por presentes.

**Trabajo pendiente detectado.** No hay imagen ni fichero de despliegue. Nada
descarga `yolo11x.pt` ni verifica su hash (R-26, R-29). `.session_state/` crece
sin política de borrado (R-30, y depende de A-02).

---

## Grafo de dependencias

```
  PLATAFORMA ······ (dependencia de cierre de todos: publica el guardia,
       ·             no bloquea el arranque de nadie)
       ·
       ·
    NUCLEO ─────────► PERCEPCION ─────────► API ─────┬─────► CLIENTE
   (métrica)          (píxeles)          (frontera)  │       (hoja)
                                                     └─────► OPERACION
                                                             (hoja)
   ───► dependencia de contrato: no se empieza sin el contrato publicado
   ····  dependencia de cierre: se empieza sin él, no se cierra sin él
```

**Dependencia de contrato frente a dependencia de cierre.** Es la distinción que
gana el paralelismo de este proyecto. `NUCLEO` no necesita que el guardia exista
para escribir cinemática; necesita que exista para poder declararse `HECHO`.
Tratar las dos cosas igual dejaría la ola 1 con un solo carril.

## Olas de paralelización

| Ola | Se puede despachar a la vez | Por qué |
|-----|----------------------------|---------|
| **1** | `PLATAFORMA`, `NUCLEO` | Ninguno depende del contrato del otro |
| **2** | `PERCEPCION` | En cuanto `NUCLEO` publique contrato |
| **3** | `API` | En cuanto `PERCEPCION` publique contrato |
| **4** | `CLIENTE`, `OPERACION` | Ambos cuelgan sólo de `API`; son hojas y no se ven entre sí |

**Ruta crítica:** `NUCLEO → PERCEPCION → API → CLIENTE`, cuatro turnos de
profundidad. Es el suelo del plazo por muchos agentes que se pongan: con dos
agentes se tarda lo mismo que con cinco, porque las olas 2 y 3 tienen un solo
carril cada una.

**El riesgo del plan** es `API`: está en la ruta crítica, es el carril más
cargado y es donde vive el único hallazgo de seguridad real. Si hay que
acelerar algo, es partirlo (plan declarado en su ficha), no añadir agentes a las
hojas.

## Matriz de trazabilidad

Cada requisito de `ANALISIS.md` tiene exactamente un carril responsable. Un
requisito sin carril es un agujero en el corte; uno con dos, una frontera mal
puesta. Lo comprueba `tools/check_carriles.py`.

| Carril | Requisitos |
|---|---|
| `PLATAFORMA` | R-18, R-23 |
| `NUCLEO` | R-04, R-05, R-07, R-09, R-14, R-20, R-22 |
| `PERCEPCION` | R-01, R-02, R-03, R-16 |
| `API` | R-08, R-10, R-13, R-15, R-17, R-19, R-21, R-24, R-25, R-27, R-28 |
| `CLIENTE` | R-06, R-11, R-12 |
| `OPERACION` | R-26, R-29, R-30 |

## Rutas compartidas y congeladas

| Ruta | Dueño | Modo | Nota |
|---|---|---|---|
| `worklog/EVENTS.jsonl` | `PLATAFORMA` | sólo añadir | Todos añaden líneas; nadie edita las previas. El guardia rechaza un diff con líneas borradas |
| `fcopilot/config.py` | `API` | propietario | `NUCLEO` y `PERCEPCION` leen constantes de dominio; añadir una clave se le pide a `API` |
| `fcopilot/__init__.py` | `NUCLEO` | propietario | Superficie pública del paquete; añadir un símbolo se le pide a `NUCLEO` |
| `tests/conftest.py` | `PLATAFORMA` | propietario | El detector guionizado que hace que la suite corra sin pesos |
| `FootballCopilot_v2.jsx` | **nadie** | congelado | Código muerto. Cualquier cambio falla el guardia hasta que se responda A-05 |

## El corte que descarté

**Alternativa considerada: cortar por funcionalidad de producto** — un carril
«métricas de jugador», otro «posesión y equipos», otro «calibración», cada uno
dueño de su trozo de backend, de API y de interfaz.

Es atractivo porque cada carril entrega valor visible solo. Lo tumbó la **regla
1 de la rúbrica**: los tres carriles necesitarían escribir en
`football_copilot_v2_backend.py`, en `fcopilot/analyzer.py` y en `App.jsx` a la
vez, así que sus conjuntos de rutas no son disjuntos y el guardia sería
imposible de escribir. También falla la **regla 4**: ninguno de los tres publica
un contrato propio, porque los tres publican trozos del mismo contrato HTTP.

Es el corte correcto para un producto que se construye desde cero por
funcionalidades. Aquí el código ya existe y está organizado por capa de
responsabilidad; imponerle un corte vertical significaría reescribirlo entero
antes de poder repartirlo.

**Segunda alternativa, descartada más rápido: un carril por módulo de
`fcopilot/`.** Once carriles con contratos de una función cada uno. Falla la
regla 4 por el otro lado —contratos tan finos que no informan de nada— y
convierte el grafo en una maraña donde cualquier cambio de forma de dato cruza
seis fronteras.
