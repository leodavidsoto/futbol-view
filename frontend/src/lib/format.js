/** Utilidades de formato y color, sin dependencias del DOM. */

export const TEAM_COLORS = {
  team_1: "#00ff88",
  team_2: "#ff3355",
  unknown: "#aaaaaa",
};

export const BALL_COLOR = "#ffdd00";

/** Color de un equipo, con reserva para valores desconocidos. */
export function teamColor(team) {
  return TEAM_COLORS[team] || TEAM_COLORS.unknown;
}

/** Convierte "#rrggbb" (o "#rgb") a rgba() con la opacidad indicada. */
export function hexToRgba(hex, alpha = 1) {
  if (typeof hex !== "string") return `rgba(0,0,0,${alpha})`;
  let value = hex.replace("#", "").trim();
  if (value.length === 3) value = value.split("").map((c) => c + c).join("");
  if (value.length !== 6 || /[^0-9a-f]/i.test(value)) return `rgba(0,0,0,${alpha})`;
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/** Segundos → "m:ss" (o "h:mm:ss" a partir de una hora). */
export function fmtTime(sec) {
  const total = Math.max(0, Math.floor(Number(sec) || 0));
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600);
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return h > 0
    ? `${h}:${mm}:${String(s).padStart(2, "0")}`
    : `${mm}:${String(s).padStart(2, "0")}`;
}

/** Metros → "845 m" / "1.24 km". */
export function fmtDistance(meters) {
  const value = Number(meters) || 0;
  return value >= 1000 ? `${(value / 1000).toFixed(2)} km` : `${Math.round(value)} m`;
}

export function fmtSpeed(kmh) {
  return `${(Number(kmh) || 0).toFixed(1)} km/h`;
}

/**
 * Zonas de intensidad. **Coinciden con `fcopilot.load.SPEED_BANDS`, y eso lo
 * comprueba una prueba** (`tests/test_gobernanza.py`), no este comentario.
 *
 * Ya divergieron: el backend pasó a los cortes de la bibliografía de GPS
 * (7,2 / 14,4 / 19,8 / 25,2 km/h) y esta tabla se quedó en los redondos
 * 7/14/20/25 con otros nombres. El resultado es de los peores que hay: la app
 * pintaba a un jugador «en carrera» mientras el informe lo contaba como
 * «trote», y las dos cifras venían del mismo sistema.
 */
export const SPEED_ZONES = [
  { name: "caminando", min: 0, max: 7.2, color: "#4a90d9" },
  { name: "trote", min: 7.2, max: 14.4, color: "#00c07f" },
  { name: "alta_velocidad", min: 14.4, max: 19.8, color: "#ffdd00" },
  { name: "muy_alta_velocidad", min: 19.8, max: 25.2, color: "#ff9500" },
  { name: "sprint", min: 25.2, max: Infinity, color: "#ff3355" },
];

export function speedZone(kmh) {
  const value = Number(kmh) || 0;
  return SPEED_ZONES.find((z) => value >= z.min && value < z.max) || SPEED_ZONES[SPEED_ZONES.length - 1];
}

/** Color según la intensidad de carrera, para pintar el número de velocidad. */
export function speedColor(kmh) {
  return speedZone(kmh).color;
}

/** Porcentaje acotado a [0, 100], listo para un ancho CSS. */
export function pct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.min(100, Math.max(0, n));
}
