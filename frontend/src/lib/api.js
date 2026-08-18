/**
 * Cliente del backend.
 *
 * Centraliza la URL base, la cabecera `x-session-id` y el manejo de errores:
 * antes cada `fetch` iba suelto por el componente y los fallos se tragaban en
 * silencio (incluido un `res.ok` que nadie comprobaba en el análisis).
 */

import { getSessionId } from "./session.js";

const RAW_API = import.meta?.env?.VITE_API_URL || "http://localhost:8000";
export const API_URL = RAW_API.replace(/\/$/, "");

const RAW_WS = import.meta?.env?.VITE_WS_URL || API_URL.replace(/^http/, "ws");
export const WS_BASE = RAW_WS.replace(/\/$/, "");

/** URL del WebSocket de cámara en vivo, con la sesión de esta pestaña. */
export function wsStreamUrl(sessionId = getSessionId()) {
  return `${WS_BASE}/ws/stream?session_id=${encodeURIComponent(sessionId)}`;
}

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function describeError(response) {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
    return JSON.stringify(body).slice(0, 200);
  } catch {
    return `HTTP ${response.status}`;
  }
}

/** `fetch` con sesión, comprobación de estado y error legible. */
export async function apiFetch(path, { method = "GET", body, signal, json = true, sessionId } = {}) {
  const headers = { "x-session-id": sessionId || getSessionId() };
  let payload = body;
  if (body !== undefined && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const response = await fetch(`${API_URL}${path}`, { method, headers, body: payload, signal });
  if (!response.ok) {
    throw new ApiError(await describeError(response), response.status);
  }
  return json ? response.json() : response;
}

export const api = {
  health: () => apiFetch("/health"),
  getConfig: () => apiFetch("/api/config"),
  setConfig: (patch) => apiFetch("/api/config", { method: "POST", body: patch }),
  setPlayerName: (trackId, name) =>
    apiFetch("/api/player-name", { method: "POST", body: { track_id: String(trackId), name } }),
  setPlayerTeam: (trackId, team) =>
    apiFetch("/api/player-team", { method: "POST", body: { track_id: String(trackId), team } }),
  calibrateScale: (pixelsPerMeter) =>
    apiFetch("/api/calibrate", { method: "POST", body: { pixels_per_meter: pixelsPerMeter } }),
  calibrateHomography: (imgPoints, worldPoints) =>
    apiFetch("/api/calibrate", {
      method: "POST",
      body: { img_points: imgPoints, world_points: worldPoints },
    }),
  getCalibration: () => apiFetch("/api/calibrate"),
  clearCalibration: () => apiFetch("/api/calibrate", { method: "DELETE" }),
  report: () => apiFetch("/api/report"),
  export: () => apiFetch("/api/export"),
  reset: (soft = false) => apiFetch(`/api/reset?soft=${soft ? "true" : "false"}`, { method: "POST" }),
  previewFrame: (blob, timestamp = 0) => {
    const form = new FormData();
    form.append("frame", blob, "frame.jpg");
    return apiFetch(`/api/preview-frame?timestamp=${encodeURIComponent(timestamp)}`, {
      method: "POST",
      body: form,
    });
  },
  processVideo: (file, signal) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch("/api/process-video", { method: "POST", body: form, signal, json: false });
  },
};
