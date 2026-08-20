/**
 * Búfer de frames analizados.
 *
 * Al reproducir el vídeo hay que localizar el frame más cercano al instante
 * actual. La versión anterior recorría todo el array en cada `timeupdate`
 * (miles de comparaciones, varias veces por segundo); aquí se usa búsqueda
 * binaria sobre `video_time`, que llega ordenado desde el backend.
 */

/** Instante de un frame, tolerando payloads incompletos. */
export function frameTime(frame) {
  const t = frame?.video_time ?? frame?.t;
  return Number.isFinite(t) ? t : 0;
}

/**
 * Índice del frame cuyo tiempo está más cerca de `time`.
 * Devuelve -1 si no hay frames.
 */
export function findFrameIndexAtTime(frames, time) {
  if (!Array.isArray(frames) || frames.length === 0) return -1;
  const target = Number(time) || 0;
  let low = 0;
  let high = frames.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (frameTime(frames[mid]) < target) low = mid + 1;
    else high = mid;
  }
  // `low` es el primer frame en o después de `target`: comparar con el previo.
  if (low > 0) {
    const prev = Math.abs(frameTime(frames[low - 1]) - target);
    const cur = Math.abs(frameTime(frames[low]) - target);
    if (prev <= cur) return low - 1;
  }
  return low;
}

/** Frame más cercano a `time`, o null. */
export function findFrameAtTime(frames, time) {
  const index = findFrameIndexAtTime(frames, time);
  return index < 0 ? null : frames[index];
}

/** Parsea un fragmento NDJSON y devuelve `{ frames, rest }`. */
export function parseNdjsonChunk(buffer, onError) {
  const lines = buffer.split("\n");
  const rest = lines.pop() ?? "";
  const frames = [];
  for (const line of lines) {
    if (!line.trim()) continue;
    try {
      frames.push(JSON.parse(line));
    } catch (error) {
      onError?.(error, line);
    }
  }
  return { frames, rest };
}

/** Resumen para la UI a partir del último frame recibido. */
export function summarizeFrame(frame) {
  const players = frame?.players || [];
  const share = frame?.possession?.share || frame?.ball?.possession_pct || {};
  return {
    players: players.length,
    team1: players.filter((p) => p.team === "team_1").length,
    team2: players.filter((p) => p.team === "team_2").length,
    topSpeed: players.reduce((max, p) => Math.max(max, Number(p.speed_kmh) || 0), 0),
    totalDistance: players.reduce((sum, p) => sum + (Number(p.total_dist_m) || 0), 0),
    sprints: players.reduce((sum, p) => sum + (Number(p.sprints) || 0), 0),
    possession: {
      team_1: Number(share.team_1) || 0,
      team_2: Number(share.team_2) || 0,
    },
  };
}
