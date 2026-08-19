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

/** Colores de banda, de menos a más intensa. */
export const BAND_COLOR = {
  caminando: "#33445a",
  trote: "#3377bb",
  alta_velocidad: "#33cc88",
  muy_alta_velocidad: "#ffcc00",
  sprint: "#ff4466",
};

export function bandColor(name) {
  return BAND_COLOR[name] || "#556";
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
