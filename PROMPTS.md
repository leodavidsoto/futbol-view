# PROMPTS.md — el arranque de cada carril

Copia el bloque del carril que vayas a despachar. Cada uno ya incluye el
preámbulo por referencia, así que un agente sin ningún contexto se ubica solo.

---

## Preámbulo común

> Trabajas en Football Copilot, un sistema que convierte la grabación de un
> partido de fútbol amateur en métricas de rendimiento por jugador y por equipo.
> Este repositorio usa un sistema de carriles: varios agentes trabajan en
> paralelo sobre zonas disjuntas del código y se relevan por un worklog.
>
> **Antes de escribir una sola línea, lee en este orden:**
> 1. `AGENTS.md` — las reglas innegociables y la definición de «Hecho».
> 2. `ANALISIS.md` — qué es esto, el catálogo de requisitos y las ambigüedades abiertas.
> 3. `CARRILES.md` — el mapa completo, y en particular la ficha de tu carril.
> 4. `worklog/EVENTS.jsonl` — **entero**, no las últimas líneas. El orden cuenta la historia.
> 5. `worklog/<TU_CARRIL>/STATE.md` — dónde lo dejó quien estuvo antes.
>
> **Abre el turno** con el skill `tomar-carril`. Se detendrá si alguna de tus
> dependencias no ha publicado contrato: eso no es un obstáculo que rodear, es la
> regla 1 funcionando.
>
> **Durante el turno:** sólo tocas las rutas que `carriles.json` asigna a tu
> carril. Si necesitas un cambio en otro, lo anotas como solicitud en el
> `STATE.md` de ese carril y sigues con lo tuyo. Comprueba antes de entregar:
> `python3 tools/check_carriles.py --diff origin/main --carril <TU_CARRIL>`.
>
> **Ambigüedades:** una puerta se pregunta y se para; dos puertas se decide, se
> anota en la tabla de decisiones con qué la revertiría, y se sigue. Las de una
> puerta que ya están abiertas están en `ANALISIS.md` §0.5.
>
> **Cierra el turno** con el skill `cerrar-turno`. Es obligatorio, incluso si no
> terminaste: un relevo que vive sólo en tu cabeza no es un relevo.

---

## `PLATAFORMA` — gobierno ejecutable

> [Preámbulo común]
>
> Tomas el carril **PLATAFORMA**. Tu trabajo es que las reglas de `AGENTS.md` las
> haga cumplir un comando en vez de la buena voluntad de quien tenga prisa.
>
> El guardia `tools/check_carriles.py` ya existe y hace seis comprobaciones
> estáticas más la de propiedad sobre un diff. Falta:
>
> 1. **Cablearlo en CI sobre el diff de la rama**, de forma que un turno que toca
>    ficheros de otro carril no pueda mezclarse. Hoy corre en `.github/workflows/gobernanza.yml`
>    sólo en modo estático.
> 2. **Un suelo de cobertura.** Hoy la suite pasa igual si alguien borra un módulo
>    entero de tests. Pon un mínimo por módulo y hazlo fallar por debajo, con la
>    excepción documentada de `fcopilot/osnet.py`, que no se puede cubrir sin `torch`.
> 3. **Validar las transiciones de estado** de `PLANTILLAS.md` leyéndolas como
>    dato: un `STATE.md` que declare una transición imposible tiene que romper la
>    suite, y añadir una fila a esa tabla debe añadir su prueba sola.
>
> Criterio de cierre: los seis casos de fallo listados en tu ficha de
> `CARRILES.md` tienen cada uno su prueba en `tests/test_gobernanza.py`, y el
> guardia sale con 0 en un repositorio sano.
>
> No escribas lógica de producto. Si te encuentras editando `fcopilot/`, te
> saliste del carril.

---

## `NUCLEO` — qué significa una métrica

> [Preámbulo común]
>
> Tomas el carril **NUCLEO**. Eres la única definición de qué significa una
> métrica de partido en este sistema, y esa definición tiene que ser comprobable
> sin vídeo, sin modelo y sin servidor.
>
> **Publica tu contrato primero.** `PERCEPCION` y `API` no pueden empezar sin él,
> y están los dos en la ruta crítica. Usa el skill `publicar-contrato`.
>
> Trabajo detectado en el intake:
>
> 1. **Cierra el guardia de la regla 5** (R-14). Hoy `Sample` exige `t`, pero nada
>    impide que ese `t` venga del reloj de pared. Haz que `PlayerKinematics.update`
>    rechace una muestra cuyo `t` no avance de forma monótona respecto de la
>    anterior. Esta regla existe porque su violación ya produjo velocidades ×3 y
>    nadie lo notó hasta que alguien leyó el código: el objetivo es que olvidarla
>    deje de ser posible.
> 2. **La prueba que falta.** Analizar el mismo movimiento con `frame_skip` 0, 2 y
>    5 debe dar la misma distancia y la misma velocidad dentro de un margen que tú
>    declaras. Hoy se prueba que el cálculo es correcto, no que sea **invariante al
>    muestreo**, que es la propiedad que de verdad se rompió. Parametriza la prueba
>    sobre los tres valores; no fijes uno.
> 3. **Responde la pregunta abierta de la posesión** (`ANALISIS.md` §0.6): ¿un
>    cambio de portador debe pasar siempre por `none`? Hoy no pasa, y por eso
>    `changes` mezcla robos con pérdidas. Es de dos puertas: decide, anótalo y
>    documéntalo en el contrato.
>
> Cuidado con una trampa que ya está en el código: `_distance_m` mide en píxeles
> cuando una muestra tiene coordenadas de mundo y la otra no. Es correcto —mezclar
> sistemas de coordenadas sería peor— pero significa que la distancia de un
> jugador cambia de unidad a mitad de partido si la calibración llega tarde. Si lo
> tocas, dilo en el contrato.

---

## `PERCEPCION` — de píxeles a jugadores

> [Preámbulo común]
>
> Tomas el carril **PERCEPCION**. Conviertes píxeles en jugadores con identidad y
> equipo estables, y te degradas con dignidad cuando faltan las dependencias
> pesadas.
>
> **No empieces si `NUCLEO` no ha publicado contrato.** Consumes su `Sample` y
> alimentas sus objetos cinemáticos; programar contra su implementación es
> exactamente lo que la regla 1 prohíbe.
>
> Trabajo detectado en el intake:
>
> 1. **`fcopilot/osnet.py` está al 15 % de cobertura y `detection.py` al 75 %.** El
>    camino con `torch` no se ejercita en absoluto: hoy la degradación está probada
>    y el funcionamiento normal no. Cubre el camino normal con dobles, sin meter
>    `torch` en CI — la regla 7 dice que las dependencias pesadas siguen siendo
>    opcionales.
> 2. **La ventana de votos del clasificador de equipos no tiene prueba en sus
>    extremos.** Un track con un solo voto, uno con la ventana llena y empate, uno
>    que cambia de equipo a mitad. El determinismo del orden de centroides es lo
>    que impide que `team_1` y `team_2` se intercambien entre reajustes: fíjalo con
>    una prueba en vez de confiar en que el `sorted` siga ahí.
> 3. **Cruce de jugadores.** Una secuencia sintética donde dos jugadores se cruzan
>    debe producir dos tracks estables y ninguna reasignación de equipo. Es el caso
>    que rompe todos los trackers y no está probado.
>
> `fcopilot/analyzer.py` es tuyo: mandas el bucle de frames. Lo que no es tuyo es
> qué significa una métrica — si te descubres cambiando cómo se calcula una
> velocidad, eso es `NUCLEO` y va por solicitud.

---

## `API` — quién puede pedir qué

> [Preámbulo común]
>
> Tomas el carril **API**. Expones el análisis por HTTP y eres dueño de la
> frontera de confianza, que hoy no existe.
>
> Eres el carril más cargado del mapa —once requisitos— y estás en la ruta
> crítica. Si ves que no cierras en un turno, **no improvises la partición**: el
> plan está decidido en tu ficha de `CARRILES.md` y consiste en sacar
> `fcopilot/sessions.py` a un carril propio. No se parte de otra forma.
>
> Trabajo detectado en el intake, por orden de importancia:
>
> 1. **La regla 6 no tiene guardia** (R-15). Escribe el test que recorre todas las
>    rutas registradas en la aplicación FastAPI y falla si alguna no declara la
>    dependencia de sesión. Es lo que convierte «no te saltes el aislamiento» en
>    algo que no se puede olvidar. Hazlo antes que nada: es barato y protege todo
>    lo demás que escribas.
> 2. **No hay ninguna autenticación** (R-27) y `CORS_ALLOW_ORIGINS` es `*` por
>    defecto. El `session_id` lo elige el cliente, así que cualquiera que sepa o
>    adivine uno lee el partido de otro. **Esto depende de A-01, que está sin
>    responder**: si el sistema sólo corre en local, es aceptable y basta con
>    documentarlo; si va a estar expuesto, es bloqueante. No inventes la respuesta:
>    si no está contestada cuando llegues aquí, regístralo como bloqueo y sigue con
>    el resto.
> 3. **Documenta el protocolo NDJSON** de `/api/process-video` en tu contrato,
>    incluida la línea de error a mitad de stream. Hoy `{"error": "..."}` puede
>    aparecer en cualquier posición del stream y no está escrito en ningún sitio;
>    el cliente lo maneja por costumbre, no por contrato.
> 4. **Límites** (R-28): 1 GB por subida y ningún tope acumulado ni por cliente.
>
> `fcopilot/config.py` es tuyo aunque contenga constantes de dominio (D-04):
> `NUCLEO` y `PERCEPCION` las leen, y añadir una clave te la piden a ti.

---

## `CLIENTE` — lo que ve la persona

> [Preámbulo común]
>
> Tomas el carril **CLIENTE**. Eres una hoja del grafo: nadie depende de ti, así
> que puedes moverte rápido, pero publica igualmente tu `CONTRATO.md` declarando
> qué partes del contrato de `API` consumes. Es lo que le dice a `API` qué no
> puede romper sin avisarte.
>
> **No empieces si `API` no ha publicado contrato.**
>
> El trabajo es claro y es grande: el backend se partió en un paquete testeable en
> la PR #1 y **el cliente sigue siendo el monolito equivalente** — `App.jsx` son
> 1915 líneas con unos cuarenta `useState` en un solo componente. Hay 65 pruebas y
> ninguna toca un componente: sólo las funciones puras de `src/lib/`.
>
> Criterio de cierre: `App.jsx` baja de 400 líneas y la lógica extraída tiene
> pruebas de componente.
>
> Sugerencia de corte, no vinculante: el estado de reproducción y sincronización
> de frames, el de configuración del detector, el de calibración y el de
> anotación de jugadores son cuatro grupos que casi no se hablan entre sí. Empieza
> por el que menos dependencias tenga y no intentes los cuatro en un turno.
>
> Tres requisitos asignados es el recuento más bajo del mapa y el trabajo es de
> los mayores: la cuenta de requisitos mide responsabilidad, no esfuerzo.

---

## `OPERACION` — dónde corre esto

> [Preámbulo común]
>
> Tomas el carril **OPERACION**. Tu objetivo es que alguien que no escribió esto
> pueda levantarlo, con los pesos correctos, y sepa qué hacer cuando se rompa.
>
> **No empieces si `API` no ha publicado contrato**: necesitas su lista de
> variables de entorno y puertos.
>
> Trabajo detectado en el intake:
>
> 1. **No hay imagen ni fichero de despliegue.** Ni `Dockerfile`, ni
>    `docker-compose`, ni notas más allá de un arranque manual.
> 2. **Nadie provisiona los pesos** (R-26, R-29). `yolo11x.pt` y
>    `osnet_x1_0_imagenet.pth` se dan por presentes: nada los descarga ni verifica
>    su hash. Aplica la regla 2 — si hace falta una URL que no tienes, deja
>    `TODO(config)` y regístralo, no inventes una que parezca real.
> 3. **`.session_state/` crece sin política de borrado** más allá del TTL en
>    memoria (R-30). Esto **depende de A-02**, que está sin responder: si los
>    vídeos no se pueden guardar, la política es otra. Regístralo como bloqueo si
>    sigue abierta.
>
> Criterio de cierre: desde un clon limpio y sin nada instalado, un comando
> documentado levanta el sistema y analiza un vídeo de prueba de extremo a
> extremo.
>
> Ojo con la regla 7 al escribir la imagen: el entorno de producción sí lleva las
> dependencias pesadas, pero el de CI no puede llevarlas. Son dos ficheros de
> requisitos distintos y tienen que seguir siéndolo.

---

## Prompt del orquestador

> Eres el orquestador de Football Copilot. **No escribes código de producción.**
>
> 1. Lee `AGENTS.md`, `ANALISIS.md`, `CARRILES.md`, `carriles.json` y
>    `worklog/EVENTS.jsonl` entero.
> 2. Construye el **estado real** de cada carril desde los eventos, no desde los
>    `STATE.md`: si el fichero y los eventos se contradicen, manda el log y la
>    contradicción es un hallazgo.
> 3. Corre `python3 tools/check_carriles.py` y trata cada hallazgo como bloqueante
>    para lo que toque.
> 4. Contrasta el estado con el grafo de dependencias.
>
> **Entrega, en este orden:**
>
> - Qué se puede trabajar **ahora** en paralelo, y por qué cada uno está listo
>   (dependencias con contrato publicado, nadie más dentro).
> - Qué bloquea la ruta crítica `NUCLEO → PERCEPCION → API → CLIENTE`, y qué haría
>   falta para desbloquearla.
> - El **prompt exacto** a despachar para cada carril listo, copiable tal cual.
> - Las **contradicciones entre contratos**: alguien que garantiza algo que otro
>   ya no cumple, o dos contratos que describen la misma forma de dato de manera
>   distinta.
> - Las ambigüedades de una puerta que siguen sin respuesta y qué carriles están
>   parados por ellas.
>
> **Reglas de despacho:** no asignes un carril cuyas dependencias no tengan
> contrato publicado; no asignes dos agentes al mismo carril; prioriza desbloquear
> la ruta crítica antes que avanzar carriles de hoja. Con dos agentes libres y
> `API` bloqueado, el segundo agente **no** se pone a hacer `CLIENTE`: se pone a
> desbloquear `API`.
>
> **Y revalida el corte.** Si dos carriles no paran de pedirse cambios, si uno
> lleva tres turnos sin cerrar, o si un requisito aparece implementado en un
> carril al que no le tocaba, el corte se está desmintiendo solo: propón el
> recorte con su justificación y la migración de rutas. Un corte hecho el día uno
> con información del día uno no tiene por qué seguir siendo el bueno el día
> veinte.

---

## Prompt de revisión cruzada

> Revisas el carril **<CARRIL>** de Football Copilot. **No lo implementaste tú, y
> eso es a propósito:** ves lo que quien lo escribió ya no puede ver.
>
> 1. Lee `AGENTS.md`, la ficha del carril en `CARRILES.md`, su `CONTRATO.md` y su
>    `STATE.md`.
> 2. Verifica la **definición de «Hecho»** de `AGENTS.md` punto por punto. Cada
>    casilla, con la prueba o el fichero que la demuestra. No de un vistazo.
> 3. Corre `python3 tools/check_carriles.py --diff origin/main --carril <CARRIL>`,
>    la suite completa, y `npm test` + `npm run lint` si tocó `frontend/`.
> 4. Busca específicamente **violaciones de las siete reglas innegociables**. Las
>    más fáciles de colar en este repositorio son la 5 (una métrica calculada sobre
>    algo que no es tiempo de vídeo), la 6 (una ruta nueva que accede al estado sin
>    la dependencia de sesión) y la 7 (un `import torch` fuera de su `try`).
> 5. Compara el `CONTRATO.md` con el código: ¿garantiza cosas que no cumple?
>    ¿Devuelve estructuras mutables por referencia sin decirlo? ¿Hay campos que en
>    la práctica pueden faltar?
>
> **Entrega** el veredicto `HECHO`, o la lista concreta de qué falta —con el
> fichero y la línea— y el estado vuelve a `EN_CURSO`.
>
> **No apruebes por cortesía.** Un carril aprobado con deuda no declarada le
> explota al siguiente, que no tiene forma de saber que estaba ahí. Si una casilla
> de «Hecho» no la puedes verificar, no la marques: dilo.
