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

/** Zonas de intensidad; deben coincidir con `fcopilot.kinematics.SPEED_ZONES`. */
export const SPEED_ZONES = [
  { name: "caminando", min: 0, max: 7, color: "#4a90d9" },
  { name: "trote", min: 7, max: 14, color: "#00c07f" },
  { name: "carrera", min: 14, max: 20, color: "#ffdd00" },
  { name: "alta_intensidad", min: 20, max: 25, color: "#ff9500" },
  { name: "sprint", min: 25, max: Infinity, color: "#ff3355" },
];

export function speedZone(kmh) {
  const value = Number(kmh) || 0;
  return SPEED_ZONES.find((z) => value >= z.min && value < z.max) || SPEED_ZONES[SPEED_ZONES.length - 1];
}

/** Color según la intensidad de carrera, para pintar el número de velocidad. */
export function speedColor(kmh) {
  return speedZone(kmh).color;
}
