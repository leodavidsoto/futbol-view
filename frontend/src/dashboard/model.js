/**
 * Lógica de presentación del panel del director técnico.
 *
 * Está separada del componente por el mismo motivo que `render/scene.js`: lo
 * que decide qué color tiene un jugador y qué frase se le enseña a alguien que
 * va a hacer un cambio se puede equivocar en silencio, y un componente de React
 * no se prueba sin montar medio navegador. Aquí no hay JSX ni hooks: entra el
 * JSON del backend, sale lo que hay que pintar.
 *
 * **No decide nada nuevo.** El semáforo lo calcula el backend, que es donde
 * están los umbrales y donde se prueban. Aquí se traduce a colores, orden y
 * frases; duplicar la decisión sería garantizar que las dos versiones se
 * separen.
 */

/** Colores del semáforo. Los nombres de estado los fija el backend. */
export const STATUS_STYLE = {
  ok:      { color: "#00ff88", bg: "#00ff8818", label: "OK" },
  vigilar: { color: "#ffcc00", bg: "#ffcc0018", label: "Vigilar" },
  cambio:  { color: "#ff4466", bg: "#ff446622", label: "Cambio" },
};

const STATUS_DESCONOCIDO = { color: "#8888aa", bg: "#8888aa18", label: "—" };

/** Estilo de un estado, tolerante a un estado que el backend añada mañana. */
export function statusStyle(status) {
  return STATUS_STYLE[status] || STATUS_DESCONOCIDO;
}

export const CONFIDENCE_STYLE = {
  alta:  { color: "#00ff88", label: "Datos fiables" },
  media: { color: "#ffcc00", label: "Con reservas" },
  baja:  { color: "#ff4466", label: "No decidas con esto" },
};

export function confidenceStyle(confidence) {
  return CONFIDENCE_STYLE[confidence] || { color: "#8888aa", label: "Sin evaluar" };
}

/**
 * ¿Se puede usar la tabla para decidir un cambio?
 *
 * Es la pregunta que el panel tiene que responder antes que ninguna otra. Un
 * `false` aquí no oculta las cifras —siguen siendo útiles para comparar
 * jugadores entre sí— pero sí tapa el semáforo, que es lo que induce a actuar.
 */
export function isActionable(quality) {
  return Boolean(quality) && quality.confidence !== "baja";
}

/**
 * Reparto de una fila en porcentajes de banda, para la barra apilada.
 *
 * Devuelve `[]` si el jugador no recorrió nada: una barra de cuatro segmentos
 * a cero se dibuja como una barra llena de un color arbitrario, que es peor
 * que no dibujar nada.
 */
export function bandShares(bands) {
  if (!bands) return [];
  const entradas = Object.entries(bands).filter(([, metros]) => Number(metros) > 0);
  const total = entradas.reduce((suma, [, metros]) => suma + Number(metros), 0);
  if (total <= 0) return [];
  return entradas.map(([nombre, metros]) => ({
    name: nombre,
    meters: Number(metros),
    pct: (Number(metros) / total) * 100,
  }));
}

/**
 * Colores de banda, de menos a más intensa.
 *
 * **Es una rampa ordinal, no una paleta categórica.** Las bandas tienen un
 * orden —caminar, trotar, correr, sprint— así que lo que tiene que leerse es
 * *más* y *menos*, no *cuál*. Por eso la claridad crece de forma monótona a lo
 * largo de la rampa: el orden se sigue viendo en escala de grises, impreso, y
 * con cualquier daltonismo.
 *
 * La versión anterior era azul-verde-amarillo-rojo, bonita y **no monótona**:
 * el rojo del sprint es más oscuro que el amarillo que va antes, así que la
 * barra apilada no se leía como una escala. Los tonos cálidos se conservan
 * porque es la convención de todo informe de GPS.
 */
export const BAND_COLOR = {
  caminando: "#3a3350",
  trote: "#8a3f7a",
  alta_velocidad: "#c8455e",
  muy_alta_velocidad: "#ef7d3c",
  sprint: "#ffc94d",
};

/** Orden de la rampa. Es dato: la leyenda y la barra lo leen de aquí. */
export const BAND_ORDER = [
  "caminando",
  "trote",
  "alta_velocidad",
  "muy_alta_velocidad",
  "sprint",
];

/** Nombres legibles. Un `muy_alta_velocidad` en pantalla es un descuido. */
export const BAND_LABEL = {
  caminando: "Caminando",
  trote: "Trote",
  alta_velocidad: "Alta",
  muy_alta_velocidad: "Muy alta",
  sprint: "Sprint",
};

export function bandColor(name) {
  return BAND_COLOR[name] || "#556";
}

export function bandLabel(name) {
  return BAND_LABEL[name] || name;
}

/**
 * Colores de equipo. Categóricos: identifican, no ordenan.
 *
 * Validados con el comprobador de paletas: separación CVD ΔE 24,9 (protan) y
 * contraste por encima de 3:1 sobre fondo oscuro. No se eligieron a ojo.
 */
export const TEAM_COLOR = { team_1: "#3d8fe0", team_2: "#c8721f", unknown: "#7a7a90" };

export function teamColor(team) {
  return TEAM_COLOR[team] || TEAM_COLOR.unknown;
}

/** Nombre legible de un equipo. */
export function teamLabel(team) {
  if (team === "team_1") return "Equipo 1";
  if (team === "team_2") return "Equipo 2";
  return "Sin asignar";
}

/**
 * Rampa secuencial del mapa de calor: un solo tono, de oscuro a claro.
 *
 * Un solo tono a propósito. Una rampa arcoíris sobre un campo inventa
 * fronteras donde el dato es continuo, y hace que el amarillo parezca «más»
 * que el rojo aunque sea menos.
 */
export const HEAT_RAMP = ["#12352a", "#1a5c42", "#22855c", "#2bb077", "#4de0a0"];

/**
 * Color de una zona según su ocupación, normalizada al máximo de la rejilla.
 *
 * Se normaliza al máximo y no a 100 % porque en una rejilla de quince zonas
 * ninguna pasa del 20 %: contra una escala fija saldría todo del mismo color
 * oscuro y el mapa no diría nada.
 */
export function heatColor(pct, max) {
  if (!max || max <= 0 || !pct) return "transparent";
  const t = Math.max(0, Math.min(1, pct / max));
  const indice = Math.min(HEAT_RAMP.length - 1, Math.floor(t * HEAT_RAMP.length));
  return HEAT_RAMP[indice];
}

/** Agrupa jugadores por equipo, con los equipos en orden estable. */
export function byTeam(players) {
  const grupos = new Map();
  for (const jugador of players || []) {
    const equipo = jugador.team || "unknown";
    if (!grupos.has(equipo)) grupos.set(equipo, []);
    grupos.get(equipo).push(jugador);
  }
  return [...grupos.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([team, members]) => ({ team, players: members }));
}

/**
 * Titular del panel: una frase, la que un DT leería de un vistazo.
 *
 * El orden importa. Si los datos no se sostienen, eso es el titular y no «dos
 * jugadores fundidos»: enseñar la conclusión antes que la advertencia es
 * exactamente cómo se toma una decisión con datos malos.
 */
export function headline(dashboard) {
  const quality = dashboard?.quality;
  if (!quality) return { tone: "neutral", text: "Sin datos todavía." };
  if (quality.confidence === "baja") {
    const critico = (quality.warnings || []).find((a) => a.level === "critico");
    return {
      tone: "bad",
      text: critico ? critico.message : "Los datos no se sostienen todavía.",
    };
  }
  const atencion = dashboard.attention || [];
  const cambios = atencion.filter((f) => f.status === "cambio");
  if (cambios.length) {
    const nombres = cambios.map((f) => f.name).join(", ");
    return {
      tone: "bad",
      text: cambios.length === 1
        ? `${nombres} ha bajado el ritmo de forma marcada.`
        : `${cambios.length} jugadores han bajado el ritmo: ${nombres}.`,
    };
  }
  if (atencion.length) {
    return { tone: "warn", text: `${atencion.length} jugadores para vigilar.` };
  }
  if (!(dashboard.players || []).length) {
    return { tone: "neutral", text: "Todavía no hay jugadores seguidos." };
  }
  return { tone: "good", text: "Nadie por debajo de su ritmo. Todo en orden." };
}

/**
 * Número para enseñar, con su unidad y sin decimales fantasma.
 *
 * `null` y `undefined` se pintan como «—», no como 0: no es lo mismo «no ha
 * corrido» que «no se sabe», y confundirlos es la mitad de los errores de un
 * panel.
 */
export function fmt(value, { unit = "", decimals = 0 } = {}) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const numero = Number(value).toFixed(decimals);
  return unit ? `${numero} ${unit}` : numero;
}

/** Porcentaje de caída con signo explícito; «—» si no hay referencia. */
export function fmtDropoff(pct) {
  if (pct === null || pct === undefined) return "—";
  const valor = Number(pct);
  return `${valor > 0 ? "+" : ""}${valor.toFixed(0)} %`;
}

/**
 * Columnas de la tabla de jugadores, en el orden en que se leen.
 *
 * Son dato para que la tabla y sus cabeceras no puedan desincronizarse: cuando
 * eran dos listas paralelas, añadir una columna en un sitio y no en el otro
 * corría todos los valores una casilla a la derecha.
 */
export const COLUMNS = [
  { key: "name",           label: "Jugador",     align: "left" },
  { key: "minutes",        label: "Min",         format: (f) => fmt(f.minutes) },
  { key: "dist_m",         label: "Distancia",   format: (f) => fmt(f.dist_m, { unit: "m" }) },
  { key: "dist_m_per_min", label: "m/min",       format: (f) => fmt(f.dist_m_per_min) },
  { key: "hi_m_per_min",   label: "Alta int.",   format: (f) => fmt(f.hi_m_per_min, { unit: "m/min" }) },
  { key: "sprints",        label: "Sprints",     format: (f) => fmt(f.sprints) },
  { key: "top_speed_kmh",  label: "Punta",       format: (f) => fmt(f.top_speed_kmh, { unit: "km/h", decimals: 1 }) },
  { key: "accelerations",  label: "Acel.",       format: (f) => fmt(f.accelerations) },
  { key: "decelerations",  label: "Fren.",       format: (f) => fmt(f.decelerations) },
  { key: "dropoff_pct",    label: "Ritmo",       format: (f) => fmtDropoff(f.dropoff_pct) },
];

/** Valor de una celda, usando el formateador declarado de la columna. */
export function cell(column, row) {
  return column.format ? column.format(row) : (row[column.key] ?? "—");
}


/**
 * Reparto de posesión entre los dos equipos, en porcentaje.
 *
 * **El objeto de posesión no tiene `team_1` en la raíz.** Tiene `seconds`,
 * `share` y `percentages`, y el panel leía la raíz: la posesión salía «— / —»
 * en pantalla mientras el backend la calculaba bien. De las tres, `share` es la
 * que un DT llama «posesión»: reparte sólo entre equipos y suma 100, ignorando
 * el tiempo en que el balón no fue de nadie.
 */
export function possessionShare(possession) {
  const share = possession?.share;
  if (!share) return { team_1: null, team_2: null };
  return { team_1: share.team_1 ?? null, team_2: share.team_2 ?? null };
}

/**
 * Duración analizada, legible.
 *
 * Por debajo de un minuto se dan segundos: «0 min analizados» sobre un clip de
 * diez segundos parece que no se analizó nada.
 */
export function fmtDuration(minutes) {
  if (minutes === null || minutes === undefined || Number.isNaN(Number(minutes))) return "—";
  const m = Number(minutes);
  if (m < 1) return `${Math.round(m * 60)} s`;
  return `${m.toFixed(m < 10 ? 1 : 0)} min`;
}

/** Fragmentación con concordancia: «1 identidad», «2,3 identidades». */
export function fmtFragmentation(value) {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  const texto = n.toFixed(1).replace(".", ",");
  return `${texto} ${n === 1 ? "identidad" : "identidades"} por jugador`;
}


// ── Comportamiento colectivo ───────────────────────────────────────────

/**
 * Convierte la ocupación del backend en una rejilla dibujable.
 *
 * El backend nombra las zonas `tercio|carril`, y ese nombre es la interfaz.
 * Aquí se parte para colocar cada celda, y se devuelve también el máximo, que
 * es lo que normaliza el color.
 */
export function zoneGrid(occupancy) {
  const zonas = occupancy?.zones;
  if (!zonas) return null;
  const tercios = [];
  const carriles = [];
  for (const nombre of Object.keys(zonas)) {
    const [tercio, carril] = nombre.split("|");
    if (!tercios.includes(tercio)) tercios.push(tercio);
    if (!carriles.includes(carril)) carriles.push(carril);
  }
  const max = Math.max(0, ...Object.values(zonas).map((z) => z.pct || 0));
  return {
    thirds: tercios,
    corridors: carriles,
    max,
    cell: (tercio, carril) => zonas[`${tercio}|${carril}`] || { seconds: 0, pct: 0 },
  };
}

/**
 * Serie temporal de una métrica colectiva, lista para dibujar.
 *
 * Descarta los bloques sin muestras en vez de dibujarlos a cero: un minuto en
 * el que no se vio al equipo no es un minuto en el que su amplitud fue cero, y
 * una línea que baja a cero y vuelve se lee como un colapso que no ocurrió.
 */
export function series(timeline, metric) {
  if (!Array.isArray(timeline)) return [];
  return timeline
    .filter((fila) => (fila.samples || 0) > 0)
    .map((fila) => ({ x: fila.from_s / 60, y: fila[metric] ?? null }))
    .filter((punto) => punto.y !== null);
}

/**
 * Las cifras colectivas que un entrenador lee primero, con su unidad.
 *
 * `length_trimmed_m` y no `length_m`: la completa la marca el portero, que
 * está treinta metros por detrás de la línea defensiva.
 */
export const COLLECTIVE_TILES = [
  { key: "width_m", label: "Amplitud", unit: "m", help: "Cuánto abre el equipo a lo ancho" },
  { key: "length_trimmed_m", label: "Longitud", unit: "m", help: "Del bloque, sin contar al portero" },
  { key: "area_m2", label: "Superficie", unit: "m²", help: "Área que ocupa el equipo" },
  { key: "spread_m", label: "Dispersión", unit: "m", help: "Distancia media al centro del equipo" },
];

/** Equipos con datos colectivos, en orden estable. */
export function collectiveTeams(collective) {
  return Object.keys(collective?.teams || {}).sort();
}

/**
 * ¿Hay bastante para enseñar la sección colectiva?
 *
 * Sin calibración el backend no acumula nada, así que `collective` llega a
 * `null` y la pestaña no debe existir. Una pestaña vacía invita a pensar que
 * algo falló.
 */
export function hasCollective(dashboard) {
  const equipos = collectiveTeams(dashboard?.collective);
  return equipos.some((e) => dashboard.collective.teams[e]?.shape?.width_m);
}
