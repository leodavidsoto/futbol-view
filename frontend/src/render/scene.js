/**
 * Dibujo del overlay sobre el vídeo.
 *
 * Todo lo de aquí son funciones puras: reciben un contexto 2D, los datos del
 * frame y unas opciones, y no saben nada de React. Vivían dentro de un
 * `useCallback` de 280 líneas en `App.jsx`, donde no había forma de probarlas:
 * cualquier comprobación exigía montar el componente entero y un canvas de
 * verdad. Aquí se prueban con un contexto de mentira que apunta cada llamada.
 *
 * Convención: cada capa recibe `(ctx, data, opts)` y no toca estado global.
 * Quien las orquesta es `drawScene`, y el orden importa: lo que se dibuja
 * después tapa lo anterior.
 */

import { BALL_COLOR, TEAM_COLORS, hexToRgba, teamColor } from "../lib/format.js";

/**
 * Dimensiones del campo, en metros.
 *
 * Es el **respaldo** cuando no se sabe en qué campo se juega, no una constante:
 * desde que la calibración usa plantillas, un partido de fútbol 7 mide 60×40 y
 * uno de sala 40×20. Dar por hecho 105×68 amontonaba a todos los jugadores de
 * un campo pequeño en la esquina superior izquierda del mini-mapa.
 */
export const FIELD_M = { width: 105, height: 68 };

/** Etiquetas y colores de las cuatro esquinas de calibración, en orden. */
export const CALIB_LABELS = ["TL", "TR", "BR", "BL"];
export const CALIB_COLORS = ["#ff4444", "#ffaa00", "#44ff44", "#4488ff"];

const MINIMAP = { width: 160, height: 96, margin: 10 };

/** Equipo efectivo: la corrección manual manda sobre la del clasificador. */
export function effectiveTeam(player, overrides = {}) {
  return overrides[player.track_id] || player.team;
}

/** Posición efectiva: si el usuario arrastró el círculo, manda su posición. */
export function effectiveCenter(player, posOverrides = {}) {
  const override = posOverrides[player.track_id];
  return override ? [override.x, override.y] : player.center;
}

// ── Capas ───────────────────────────────────────────────────────────────
export function drawPossessionBar(ctx, data, { width }) {
  const pct = data.ball?.possession_pct;
  if (!pct) return;
  const { team_1: t1 = 0, team_2: t2 = 0 } = pct;
  const total = t1 + t2 || 1;
  const share = t1 / total;
  ctx.fillStyle = TEAM_COLORS.team_1;
  ctx.fillRect(0, 0, width * share, 5);
  ctx.fillStyle = TEAM_COLORS.team_2;
  ctx.fillRect(width * share, 0, width * (1 - share), 5);
}

export function drawHeatmap(ctx, data, { overrides }) {
  (data.players || []).forEach((player) => {
    const color = teamColor(effectiveTeam(player, overrides));
    const trail = player.trail || [];
    trail.forEach((point, i) => {
      ctx.beginPath();
      ctx.arc(point.x, point.y, 14, 0, Math.PI * 2);
      ctx.fillStyle = hexToRgba(color, (i / trail.length) * 0.28);
      ctx.fill();
    });
  });
}

export function drawBoundingBoxes(ctx, data, { overrides }) {
  (data.players || []).forEach((player) => {
    const [x1, y1, x2, y2] = player.bbox;
    ctx.strokeStyle = hexToRgba(teamColor(effectiveTeam(player, overrides)), 0.45);
    ctx.lineWidth = 1;
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
  });
  if (data.ball?.bbox) {
    const [x1, y1, x2, y2] = data.ball.bbox;
    ctx.strokeStyle = hexToRgba(BALL_COLOR, 0.6);
    ctx.lineWidth = 1;
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
  }
}

export function drawBallTrail(ctx, data, { trailLength }) {
  const full = data.ball?.trail;
  if (!full || full.length <= 1) return;
  const trail = full.slice(-trailLength);
  ctx.beginPath();
  ctx.moveTo(trail[0].x, trail[0].y);
  trail.forEach((point) => ctx.lineTo(point.x, point.y));
  ctx.strokeStyle = hexToRgba(BALL_COLOR, 0.35);
  ctx.lineWidth = 2.5;
  ctx.lineJoin = "round";
  ctx.stroke();
  trail.forEach((point, i) => {
    const t = i / trail.length;
    ctx.beginPath();
    ctx.arc(point.x, point.y, 2 + t * 5, 0, Math.PI * 2);
    ctx.fillStyle = hexToRgba(BALL_COLOR, 0.15 + t * 0.65);
    ctx.fill();
  });
}

export function drawPlayers(ctx, data, opts) {
  const {
    overrides = {},
    posOverrides = {},
    playerNames = {},
    selectedTrackId = null,
    draggingTrackId = null,
    circleRadius = 22,
    trailLength = 20,
    showNames = true,
    showSpeed = true,
    showDistance = false,
    showTrails = true,
  } = opts;

  (data.players || []).forEach((player) => {
    const [cx, cy] = effectiveCenter(player, posOverrides);
    const color = teamColor(effectiveTeam(player, overrides));
    const isSelected = selectedTrackId === player.track_id;
    const isDragging = draggingTrackId === player.track_id;
    const r = circleRadius;

    if (isDragging) {
      ctx.setLineDash([5, 3]);
      ctx.beginPath();
      ctx.arc(cx, cy, r + 10, 0, Math.PI * 2);
      ctx.strokeStyle = hexToRgba(color, 0.7);
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.setLineDash([]);
    }

    ctx.shadowColor = color;
    ctx.shadowBlur = isDragging ? 35 : isSelected ? 28 : 12;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = color;
    ctx.lineWidth = isDragging ? 3.5 : isSelected ? 4 : 2.5;
    ctx.stroke();
    ctx.fillStyle = hexToRgba(color, isDragging ? 0.28 : 0.15);
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();

    if (showNames) {
      const name = playerNames[player.track_id] || player.name || `#${player.track_id}`;
      ctx.font = "bold 12px 'Segoe UI', Arial, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      const textWidth = ctx.measureText(name).width;
      ctx.fillStyle = "rgba(0,0,0,0.65)";
      ctx.fillRect(cx - textWidth / 2 - 4, cy - r - 18, textWidth + 8, 15);
      ctx.fillStyle = color;
      ctx.fillText(name, cx, cy - r - 4);
    }

    const muestraVelocidad = showSpeed && player.speed_kmh > 0.5;
    if (muestraVelocidad) {
      ctx.font = "10px monospace";
      ctx.fillStyle = "rgba(255,255,255,0.75)";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(`${player.speed_kmh} km/h`, cx, cy + r + 4);
    }

    if (showDistance && player.total_dist_m > 0) {
      // Si la velocidad ya ocupó la línea de debajo, la distancia baja una más.
      const offset = muestraVelocidad ? r + 16 : r + 4;
      ctx.font = "9px monospace";
      ctx.fillStyle = "rgba(200,200,200,0.55)";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(`${player.total_dist_m} m`, cx, cy + offset);
    }

    if (showTrails && player.trail?.length > 1) {
      const trail = player.trail.slice(-trailLength);
      trail.forEach((point, i) => {
        ctx.beginPath();
        ctx.arc(point.x, point.y, 3, 0, Math.PI * 2);
        ctx.fillStyle = hexToRgba(color, (i / trail.length) * 0.35);
        ctx.fill();
      });
    }
  });
}

export function drawBall(ctx, data) {
  if (!data.ball) return;
  const [x, y] = data.ball.center;
  ctx.shadowColor = BALL_COLOR;
  ctx.shadowBlur = 22;
  ctx.beginPath();
  ctx.arc(x, y, 13, 0, Math.PI * 2);
  ctx.fillStyle = BALL_COLOR;
  ctx.globalAlpha = 0.95;
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.shadowBlur = 0;
  ctx.font = "bold 11px Arial";
  ctx.fillStyle = "#000";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("⚽", x, y);
}

/**
 * Proyecta un punto al mini-mapa.
 *
 * Con calibración se usan metros reales del campo; sin ella, la proporción
 * dentro del frame. Son dos sistemas de coordenadas distintos y el mini-mapa
 * es el único sitio donde conviven, así que la elección se hace una vez y para
 * todos los jugadores del frame: mezclar los dos pondría a unos en su sitio y
 * a otros no.
 */
export function projectToMinimap(point, { useWorld, box, frame, field = FIELD_M }) {
  const [x, y] = point;
  if (useWorld) {
    return [
      box.x + (x / field.width) * box.width,
      box.y + (y / field.height) * box.height,
    ];
  }
  return [box.x + (x / frame.width) * box.width, box.y + (y / frame.height) * box.height];
}

export function drawMinimap(ctx, data, { width, height, overrides = {}, posOverrides = {}, field = FIELD_M }) {
  if (!data.players?.length) return;
  const box = {
    x: width - MINIMAP.width - MINIMAP.margin,
    y: height - MINIMAP.height - MINIMAP.margin,
    width: MINIMAP.width,
    height: MINIMAP.height,
  };

  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.beginPath();
  ctx.roundRect(box.x - 4, box.y - 4, box.width + 8, box.height + 8, 6);
  ctx.fill();
  ctx.fillStyle = "#1a4d1a";
  ctx.fillRect(box.x, box.y, box.width, box.height);

  ctx.strokeStyle = "rgba(255,255,255,0.3)";
  ctx.lineWidth = 0.5;
  ctx.strokeRect(box.x, box.y, box.width, box.height);
  ctx.beginPath();
  ctx.moveTo(box.x + box.width / 2, box.y);
  ctx.lineTo(box.x + box.width / 2, box.y + box.height);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(box.x + box.width / 2, box.y + box.height / 2, box.height * 0.18, 0, Math.PI * 2);
  ctx.stroke();
  const areaHeight = box.height * 0.3;
  ctx.strokeRect(box.x, box.y + (box.height - areaHeight) / 2, box.width * 0.12, areaHeight);
  ctx.strokeRect(
    box.x + box.width - box.width * 0.12,
    box.y + (box.height - areaHeight) / 2,
    box.width * 0.12,
    areaHeight,
  );

  const frame = { width, height };
  const useWorld = data.players.some((p) => p.world_pos);

  data.players.forEach((player) => {
    // La elección de sistema de coordenadas se hizo una vez para todo el frame,
    // y aquí se respeta. Antes se decidía por jugador: con calibración, uno sin
    // `world_pos` caía a proyección por píxeles y aparecía en un punto del
    // mini-mapa que no tiene nada que ver con dónde está — mezclando en el
    // mismo dibujo dos sistemas de coordenadas, que es justo lo que el contrato
    // de `projectToMinimap` dice que no se hace. No pintarlo es mejor que
    // pintarlo mal: un hueco se ve, una posición falsa no.
    if (useWorld && !player.world_pos) return;
    const color = teamColor(effectiveTeam(player, overrides));
    const point = useWorld ? player.world_pos : effectiveCenter(player, posOverrides);
    const [px, py] = projectToMinimap(point, { useWorld, box, frame, field });
    ctx.beginPath();
    ctx.arc(px, py, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = 4;
    ctx.fill();
    ctx.shadowBlur = 0;
  });

  if (data.ball) {
    const world = data.ball.world_pos;
    const [px, py] = projectToMinimap(world || data.ball.center, {
      useWorld: Boolean(world),
      box,
      frame,
      field,
    });
    ctx.beginPath();
    ctx.arc(px, py, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = BALL_COLOR;
    ctx.shadowColor = BALL_COLOR;
    ctx.shadowBlur = 5;
    ctx.fill();
    ctx.shadowBlur = 0;
  }
}

export function drawCalibration(ctx, { calibrating, calibPoints = [] }) {
  calibPoints.forEach((point, i) => {
    ctx.beginPath();
    ctx.arc(point.x, point.y, 9, 0, Math.PI * 2);
    ctx.fillStyle = CALIB_COLORS[i];
    ctx.globalAlpha = 0.85;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.font = "bold 10px monospace";
    ctx.fillStyle = "#000";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(CALIB_LABELS[i], point.x, point.y);
  });
  if (calibrating) {
    const next = CALIB_LABELS[calibPoints.length];
    ctx.font = "bold 13px sans-serif";
    ctx.fillStyle = CALIB_COLORS[calibPoints.length] || "#fff";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(`Click → ${next} (${calibPoints.length}/4)`, 12, 12);
  }
}

// ── Orquestador ─────────────────────────────────────────────────────────
/**
 * Dibuja el frame completo. El orden de las capas es el orden de apilado.
 */
export function drawScene(ctx, canvas, data, opts = {}) {
  if (!ctx || !canvas || !data) return false;
  const { width, height } = canvas;
  const capa = { ...opts, width, height };

  ctx.clearRect(0, 0, width, height);
  if (opts.showPossessionBar) drawPossessionBar(ctx, data, capa);
  if (opts.showHeatmap) drawHeatmap(ctx, data, capa);
  if (opts.showBBoxes) drawBoundingBoxes(ctx, data, capa);
  if (opts.showTrails) drawBallTrail(ctx, data, capa);
  drawPlayers(ctx, data, capa);
  drawBall(ctx, data);
  if (opts.showMiniMap) drawMinimap(ctx, data, capa);
  if (opts.calibrating || opts.calibPoints?.length) drawCalibration(ctx, capa);
  return true;
}
