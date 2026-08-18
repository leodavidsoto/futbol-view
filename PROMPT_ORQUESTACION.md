# Prompt: montar el sistema de carriles y relevo en un proyecto nuevo

Copia todo lo que está entre las líneas de guiones y pégalo como primer mensaje
en el proyecto donde quieras montar esto. **No tienes que analizar nada antes:**
pega tu encargo tal como lo tengas —un párrafo, una conversación, un pliego, un
repositorio existente— y el orquestador hace el análisis, el catálogo y el corte
de carriles. Esa es la diferencia con la versión anterior, que te obligaba a
llegar con el proyecto ya descompuesto en la cabeza.

---

Vas a montar el andamiaje de orquestación multiagente de este repositorio. No
escribes código de producción todavía: construyes el sistema que permite que
varios agentes trabajen en paralelo sin pisarse y que cualquiera retome sin
contexto previo.

**Tú haces el análisis.** No supongas que yo llego con el proyecto descompuesto.
Yo te doy material en bruto; tú lo lees, lo catalogas, decides dónde cortar y me
enseñas el corte con su justificación. Si te devuelvo el trabajo de descomponer
—"dime tú qué carriles quieres"— has fallado en lo principal del encargo.

## Mi encargo

<pega aquí lo que tengas: la idea en dos frases, el hilo de chat donde la
discutimos, el pliego del cliente, el README del repo que hay que rehacer, o
simplemente "mira el código que ya está y dime". Sin formato. Sin campos que
rellenar. Puede estar incompleto y contradecirse; parte de tu trabajo es
detectarlo.>

**Si además hay código en el repositorio**, léelo: cuenta como fuente primaria y
manda sobre lo que diga la documentación cuando ambos se contradigan. Una
contradicción entre código y documento es un hallazgo, no un detalle: anótala.

---

# Fase 0 — Intake: leer, catalogar, y decir qué falta

Antes de cortar nada, produce `ANALISIS.md`. Este documento es la razón de ser
del encargo: es donde demuestras que entendiste el problema, y es lo que me
permite pillarte un malentendido cuando corregirlo todavía cuesta barato.

Debe contener, en este orden:

### 0.1 El objetivo, reformulado por ti

Una sola frase, con tus palabras, no las mías. Si tu frase y mi encargo dicen
cosas distintas, uno de los dos está mal y hay que saberlo ahora.

Debajo, tres o cuatro frases de contexto: para quién es, qué sustituye, qué pasa
si no existe.

### 0.2 Inventario del dominio

Cuatro listas, extraídas del material, no inventadas:

- **Entidades** — los sustantivos que el sistema guarda o manipula. Marca cuáles
  tienen identidad propia y ciclo de vida, y cuáles son datos de otra entidad.
- **Capacidades** — los verbos. Qué se le puede pedir al sistema.
- **Actores** — quién invoca cada capacidad. Incluye los no humanos: cron,
  webhooks, otros servicios.
- **Integraciones externas** — todo lo que está fuera de tu control y puede
  fallar, caducar, cambiar de contrato o cobrar por uso.

### 0.3 Catálogo de requisitos

Una tabla. Es la pieza que hace verificable todo lo que viene después:

| ID | Requisito | Tipo | Origen | Confianza |
|----|-----------|------|--------|-----------|
| R-01 | … | funcional / transversal / regla-de-dominio / operativo | cita literal / inferido / ausente | alta / media / baja |

Reglas de la tabla:

- **`Origen: cita literal`** significa que puedes señalar la frase exacta del
  material. **`inferido`** significa que lo dedujiste; entonces la celda debe
  decir *de qué* lo dedujiste. **`ausente`** es un requisito que el material no
  menciona pero que el sistema no puede no tener —autenticación, migraciones,
  qué pasa en un reintento—; los inventas tú porque nadie los escribe nunca, y
  los marcas así para que yo pueda tacharlos.
- **`Confianza: baja`** obliga a que ese requisito aparezca en el registro de
  ambigüedades (0.5).
- Cada ID vive para siempre. Si un requisito cambia, se añade una fila nueva que
  supersede a la anterior y se anota cuál; no se edita en el sitio.

### 0.4 Restricciones transversales y su guardia

No te las voy a dar. Dedúcelas del catálogo: si hay datos de varios clientes,
hay aislamiento; si hay dinero, hay idempotencia y auditoría; si hay datos
personales, hay una regla sobre qué nunca sale en un log; si hay reintentos, hay
una regla sobre qué es seguro repetir.

Por cada una, una fila:

| Restricción | Qué pasa si alguien la olvida | Guardia | Dónde vive |
|---|---|---|---|
| … | … | … | … |

La columna **"qué pasa si alguien la olvida"** decide el resto. Si la respuesta
es *"nada, hasta que explote en producción"*, la restricción **no puede quedarse
en la documentación**: necesita un guardia en el código, y lo diseñas aquí, no
después. Ver la Fase 3.

### 0.5 Registro de ambigüedades

Una tabla con toda decisión que el material no resuelve:

| ID | La duda | Puertas | Mi decisión provisional | Qué la revierte |
|----|---------|---------|-------------------------|-----------------|

**Puertas** es lo que decide si me preguntas o no:

- **Una puerta** — equivocarse cuesta rehacer trabajo ya hecho, migrar datos ya
  escritos, o romper algo publicado. Elegir el motor de base de datos, el
  formato de un identificador que va a viajar a sistemas de terceros, si el
  sistema es multi-tenant. **Estas me las preguntas, y paras.**
- **Dos puertas** — equivocarse cuesta un rato de trabajo y ya. La forma de un
  DTO interno, el nombre de un módulo, la librería de fechas. **Estas las tomas
  tú, las anotas con su reversa, y sigues.**

Al clasificar, ten en cuenta el momento: una decisión de dos puertas hoy puede
tener una sola dentro de tres carriles, cuando ya haya código encima. Si te
parece que es el caso, dilo en la fila.

**No me preguntes más de cinco cosas.** Si te salen más de cinco de una puerta,
es que estás clasificando mal por prudencia: revisa cuáles son de verdad caras
de revertir. Las preguntas van todas juntas al final, no goteando.

### 0.6 Tablas de dominio

Si del material sale una tabla —estados y transiciones válidas, vocabulario
cerrado, matriz de decisiones, tarifas, permisos por rol— transcríbela **entera
y aquí**, y marca que el código debe implementarla como dato, no como
condicionales (Fase 3).

Si el material *implica* una máquina de estados sin dibujarla, dibújala tú y
márcala como inferida. Preguntar "¿se puede pasar de X a Z directamente?" es una
de las pocas preguntas que casi siempre vale la pena hacer.

### 0.7 Lo que no encontré

Lista explícita de lo que buscaste en el material y no estaba: volumen esperado,
latencia aceptable, quién opera esto en producción, presupuesto de
infraestructura, plazos, qué pasa con los datos que ya existen. No es un
reproche: es lo que me dice qué tengo que ir a averiguar mientras tú avanzas.

---

# Fase 1 — El corte: de catálogo a carriles

Ahora, y sólo ahora, cortas. Un carril es una unidad asignable a **un** agente
por turno.

### 1.1 El criterio de corte

Corta por **razón de cambio y propiedad del dato**, no por capa técnica.

Un corte en "frontend / backend / base de datos" fabrica dependencias en todas
las direcciones: cada funcionalidad toca los tres, así que los tres carriles se
bloquean entre sí y ninguno cierra hasta que cierran todos. Un corte por
capacidad vertical —cada carril dueño de sus entidades, su lógica y su
superficie— produce carriles que cierran solos.

Excepción legítima: una capa que es *infraestructura de verdad* para todos los
demás —el acceso a datos que inyecta el filtro de tenant, el bus de eventos, el
motor de estados— sí es su propio carril, y es casi siempre el primero. La
prueba para distinguirla: si su contrato lo consumen tres o más carriles y ella
no consume el de nadie, es infraestructura; si sólo la usa uno, no es un carril,
es una parte de ese carril.

### 1.2 La rúbrica

Cada carril candidato pasa estas siete comprobaciones. Un candidato que falle
una no es un carril: fusiónalo, pártelo o reasigna sus archivos.

1. **Un dueño por ruta.** Los conjuntos de rutas de archivo de dos carriles son
   disjuntos. Sin mapa de propiedad, "no toques otro carril" es una convención
   que nadie puede verificar; con el mapa, se comprueba con un `git diff`.
2. **Las rutas compartidas tienen dueño único.** Configuración, esquema de
   datos, definiciones de tipos comunes: uno manda y los demás piden. Dilo
   explícitamente, con nombre.
3. **Cierra con una prueba.** El criterio de cierre es algo que una prueba
   demuestra, no "está bien hecho". Si no sabes escribir esa prueba, el carril
   está mal definido.
4. **Publica exactamente un contrato.** Cero contratos = no es un carril
   independiente. Dos o más = son dos carriles.
5. **No hay ciclos.** Si A depende de B y B de A, o el corte está mal, o falta
   extraer lo compartido a un tercer carril.
6. **Cabe en un turno.** Si su criterio de cierre necesita más de tres o cuatro
   contratos ajenos, o si al describirlo usas "y además", pártelo.
7. **Se puede probar sin sus dependientes.** Un carril que sólo se puede probar
   arrancando medio sistema no está aislado.

### 1.3 La matriz de trazabilidad

Tabla de dos columnas: cada **ID del catálogo** (0.3) → **el carril** que lo
implementa.

- Un requisito sin carril es un agujero en el corte.
- Un requisito en dos carriles es una frontera mal puesta.
- Un carril sin requisitos es trabajo que nadie pidió.

Las tres cosas se ven de un vistazo en esta tabla y en ningún otro sitio. Por eso
es obligatoria.

### 1.4 El corte que descartaste

Enseña **al menos una descomposición alternativa** que consideraste, y por qué
la rúbrica la tumbó. Un solo corte presentado sin alternativa es indistinguible
del primero que se te ocurrió, y yo no tengo forma de juzgarlo.

### 1.5 Presupuesto de paralelismo

Del grafo de dependencias salen las olas. Dime, por ola: cuántos carriles se
pueden despachar a la vez, y cuál es la **ruta crítica** —la cadena más larga de
dependencias, que es lo que fija el suelo del plazo por muchos agentes que
pongas—. Si la ola 1 tiene un solo carril y todo cuelga de él, dilo: es el riesgo
principal del plan y a lo mejor merece partirse.

---

# Fase 2 — Los entregables

Cuatro documentos en la raíz, un directorio `worklog/`, y cinco skills en
`.claude/skills/`. Más `ANALISIS.md` de la Fase 0. Nada más: el código de
producción viene después, en turnos separados, uno por carril.

### `AGENTS.md` — el contrato de trabajo

Lo primero que lee cualquier agente:

- **Qué construimos** y el stack, en una tabla, con la marca de cuáles casillas
  las decidiste tú (vienen del registro de ambigüedades) y cuáles me las diste
  yo. Proponer alternativas requiere abrir un ADR.
- **Reglas innegociables**, numeradas, derivadas de la tabla 0.4 y con su
  guardia al lado. Incluye siempre estas cuatro, adaptadas:
  1. *Contrato antes que código.* Ningún carril se implementa hasta que su
     contrato esté publicado. Los demás programan contra el contrato, no contra
     la implementación.
  2. *No inventes credenciales ni datos de proveedor.* Si falta un token o una
     URL, deja un `TODO(config)` explícito y regístralo como bloqueo. No
     hardcodees valores de ejemplo que parezcan reales.
  3. *Un agente = un carril por turno.* No toques archivos de un carril que no te
     fue asignado. Si necesitas un cambio ahí, regístralo como solicitud en el
     worklog de ese carril.
  4. *Las correcciones no borran historia.* Se corrigen con un registro
     compensatorio, no con un `DELETE`.
- **Cómo registrar el trabajo**: el formato exacto de la línea de
  `EVENTS.jsonl`, con un ejemplo real.
- **Estados válidos:** `NO_INICIADO` → `EN_CURSO` → `LISTO_PARA_REVISION` →
  `HECHO`. Fuera de la línea: `BLOQUEADO`, que exige `bloqueos` no vacío.
- **Definición de "Hecho"**, como checklist.
- **Qué hacer ante una ambigüedad**: la regla de las puertas de 0.5, para que
  todos los agentes la apliquen igual, no sólo tú.

### `CARRILES.md` — el mapa

Por carril: objetivo en una frase, de qué depende, qué contrato publica, **qué
rutas de archivo le pertenecen**, y criterio de cierre verificable.

Además: el grafo de dependencias en ASCII, las olas de paralelización, la matriz
de trazabilidad (1.3) y el corte descartado (1.4).

Las tablas de dominio de 0.6 van **aquí**, marcadas como fuente de verdad.

### `PROMPTS.md` — el arranque de cada carril

Un preámbulo común —qué leer, en qué orden, qué hacer al terminar— y un prompt
por carril que lo usa. Más dos que no son de carril:

- **Orquestador.** Lee el worklog completo, construye el estado real, lo
  contrasta con el grafo, y entrega: qué se puede trabajar ahora en paralelo, qué
  bloquea la ruta crítica, el prompt exacto a despachar para cada carril listo, y
  las contradicciones entre contratos.
- **Revisión cruzada.** La hace un agente que no implementó el carril, y eso es a
  propósito.

### `PLANTILLAS.md`

Plantillas de `STATE.md` y `CONTRATO.md`, más un ejemplo de `EVENTS.jsonl`.

`STATE.md` lleva: estado, último agente, última actualización, contrato publicado
sí/no, qué está hecho, qué falta, bloqueos activos, **tabla de decisiones con
columna "reversible"**, y **notas para quien retome**.

Esas dos últimas son las que más sirven al que llega después: la tabla de
decisiones evita que alguien revierta algo por no saber por qué está así, y las
notas recogen lo que no es obvio leyendo el código —trampas, supuestos, cosas
que se probaron y no funcionaron—.

### `worklog/`

- `worklog/README.md` — qué hay acá y las reglas de escritura.
- `worklog/EVENTS.jsonl` — con la primera línea del orquestador: el corte hecho.
- `worklog/<CARRIL>/STATE.md` por carril, todos en `NO_INICIADO`, cada uno ya
  diciendo de qué depende, qué le toca y **qué IDs del catálogo cubre**.

---

# Los cinco skills

Van en `.claude/skills/<nombre>/SKILL.md`, con frontmatter `name` y
`description`. La descripción decide cuándo se invocan solos, así que sé
específico.

### `tomar-carril`
Ritual de apertura. El agente: lee `AGENTS.md`, `CARRILES.md` y `EVENTS.jsonl`
completo; lee el `STATE.md` de su carril; **verifica que cada dependencia tenga
`CONTRATO.md` publicado** y se detiene si falta uno —no se programa contra una
implementación—; confirma que ningún otro agente lo tenga `EN_CURSO`; marca
`EN_CURSO` y anota la línea de apertura.

### `cerrar-turno`
Ritual de cierre, **obligatorio**. Actualiza `STATE.md` con estado real,
decisiones y notas; agrega **una** línea a `EVENTS.jsonl` por **append** —nunca
reescribiendo líneas previas—; commitea y **pushea**. El push va en el skill
porque un relevo que vive sólo en el disco local no es un relevo.

### `publicar-contrato`
Escribe `CONTRATO.md`: qué expone, esquemas concretos (no descripciones), tabla
de errores con qué debe hacer quien llama, **qué NO expone**, y qué carriles
dependen de él. Advierte que un contrato que miente es peor que uno ausente.

### `revisar-carril`
La revisión cruzada. Verifica la definición de "Hecho" punto por punto, corre el
checklist de cumplimiento, y busca específicamente las violaciones de las reglas
innegociables. **Comprueba que los IDs del catálogo asignados al carril estén de
verdad implementados**, no sólo que el código funcione. Entrega veredicto `HECHO`
o la lista concreta de qué falta. Le dice explícitamente: no apruebes por
cortesía.

### `orquestar`
Construye el estado real desde el worklog, lo contrasta con el grafo y despacha.
No escribe código de producción. Reglas: no asignar un carril cuyas dependencias
no tengan contrato; no asignar dos agentes al mismo carril; priorizar desbloquear
la ruta crítica antes que avanzar carriles de hoja.

Y una responsabilidad que no es de despacho sino de análisis: **revalidar el
corte**. En cada pasada comprueba si la realidad lo desmintió —dos carriles que
no paran de pedirse cambios el uno al otro, un carril que lleva tres turnos sin
cerrar, un requisito que aparece implementado en un carril que no le tocaba—. Si
lo desmintió, propone el recorte con su justificación y la migración de rutas.
Un corte hecho el día uno con información del día uno no tiene por qué seguir
siendo el bueno el día veinte.

### Cuando llega material nuevo

Requisitos nuevos a mitad de proyecto no se parchean a mano en `CARRILES.md`.
Se vuelve a Fase 0 en modo *delta*: qué IDs se añaden, cuáles quedan
superseded, qué carriles cambian de alcance, y qué contratos publicados quedan
mintiendo. Eso último es lo importante: un contrato que dejó de ser cierto y
sigue publicado envenena a todos los carriles que programaron contra él.

---

# Fase 3 — Lo que hace que esto funcione de verdad

Un sistema de gobierno que sólo documenta reglas se degrada en cuanto alguien
tiene prisa. Aplica estos cuatro patrones.

### Las reglas críticas las hace cumplir el código

Ya rellenaste la columna "qué pasa si alguien la olvida" en 0.4. Para cada fila
donde la respuesta era "nada, hasta producción", el guardia es obligatorio y se
diseña junto con la regla.

La forma buena de un guardia es **hacer imposible el error**, no detectarlo. En
un repo real, "toda consulta filtra por tenant" no quedó como advertencia: el
acceso a datos pasa por una clase que inyecta el filtro y **no expone ninguna
forma de consultar sin él**. Olvidarlo dejó de ser posible. Lo mismo con "nadie
cambia el estado fuera del motor": la vía genérica de actualización **rechaza**
esa columna con un error que además dice por dónde ir.

### Cuando un cambio requiere dos pasos, el segundo falla ruidosamente

Si añadir una tabla exige DDL **y** registrarla en una lista, omitir el segundo
paso tiene que dar un error inmediato y explícito, no un comportamiento
silencioso. En el repo original eso salvó de un bug real: el segundo paso se
olvidó, y el sistema lo dijo en el acto en vez de dejar una tabla sin
aislamiento.

### Los checklists son código ejecutable

Una lista que alguien tilda de memoria no detecta nada. Escribe las
verificaciones automatizables como un módulo que se corre con un comando y sale
con código 1 si encuentra hallazgos, y **métela en la suite de pruebas** para que
falle sola. Lo que no se puede automatizar va como preguntas explícitas que el
informe imprime, para que el revisor sepa qué le toca a él.

La comprobación de propiedad de rutas (1.2, regla 1) entra aquí: es un script que
lee `CARRILES.md`, mira el diff y falla si un carril tocó archivos que no son
suyos.

### Las tablas de dominio van como dato, no como condicionales

Las tablas de 0.6 se implementan como estructura de datos y se **validan al
importar**, para que un error de tipeo reviente al arrancar y no en producción.
Y las pruebas se generan desde esa misma tabla: así añadir una fila añade su
prueba sola, y nadie puede sumar un caso y olvidar probarlo.

---

# Dos cosas que aprendimos a los golpes

**Las pruebas de concurrencia encuentran lo que ninguna prueba secuencial ve.**
Si el spec pide "enviar lo mismo N veces produce un solo registro", escríbela con
hilos de verdad. En el repo original esa prueba destapó que la conexión
compartida no era segura entre hilos, algo que habría aparecido en producción y
no en desarrollo.

**Las pruebas que dependen de la fecha de hoy fallan meses después.** Si afirmas
que algo "corre la fecha hacia adelante", fija el día en la prueba o afirma `>=`.
Hay una prueba así en el repo original que pasó al escribirse y falla hoy.

---

# Cómo terminas

Tu último mensaje debe decirme, en este orden:

1. **El objetivo tal como lo entendiste** (0.1), primero de todo, para que pueda
   pararte en la primera línea si no nos entendimos.
2. **Los carriles y por qué cortaste ahí** — con la alternativa que descartaste y
   qué regla de la rúbrica la tumbó.
3. **Qué se puede despachar ahora en paralelo**, y cuál es la ruta crítica.
4. **El prompt exacto del primer carril**, listo para copiar.
5. **Lo que decidí yo por ti** — la lista de dos puertas, con su reversa, para
   que la ojees sin tener que aprobarla.
6. **Lo que necesito que me respondas** — máximo cinco, sólo de una puerta, cada
   una con tu recomendación por defecto para que puedas contestar "sí a todo".

No implementes ningún carril en este turno. El andamiaje primero.
