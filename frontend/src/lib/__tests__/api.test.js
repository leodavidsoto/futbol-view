import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, API_URL, api, apiFetch, wsStreamUrl } from "../api.js";
import { SESSION_STORAGE_KEY } from "../session.js";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => body,
  };
}

beforeEach(() => {
  globalThis.sessionStorage = {
    store: { [SESSION_STORAGE_KEY]: "sesion-de-prueba" },
    getItem(k) { return this.store[k] ?? null; },
    setItem(k, v) { this.store[k] = v; },
    removeItem(k) { delete this.store[k]; },
  };
  globalThis.fetch = vi.fn(async () => jsonResponse({ ok: true }));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiFetch", () => {
  it("añade la cabecera de sesión a cada petición", async () => {
    await apiFetch("/api/config");
    const [url, init] = globalThis.fetch.mock.calls[0];
    expect(url).toBe(`${API_URL}/api/config`);
    expect(init.headers["x-session-id"]).toBe("sesion-de-prueba");
  });

  it("serializa el cuerpo JSON", async () => {
    await apiFetch("/api/config", { method: "POST", body: { imgsz: 640 } });
    const [, init] = globalThis.fetch.mock.calls[0];
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ imgsz: 640 });
  });

  it("no toca el Content-Type de un FormData", async () => {
    const form = new FormData();
    await apiFetch("/api/preview-frame", { method: "POST", body: form });
    const [, init] = globalThis.fetch.mock.calls[0];
    expect(init.headers["Content-Type"]).toBeUndefined();
    expect(init.body).toBe(form);
  });

  it("convierte un error HTTP en ApiError con el detalle del backend", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse({ detail: "imgsz: fuera de rango [320, 2048]" }, { ok: false, status: 400 }));
    await expect(apiFetch("/api/config")).rejects.toBeInstanceOf(ApiError);
    await expect(apiFetch("/api/config")).rejects.toThrow(/fuera de rango/);
  });

  it("entiende los errores de validación de FastAPI", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse({ detail: [{ msg: "name vacio" }] }, { ok: false, status: 422 }));
    await expect(apiFetch("/api/player-name")).rejects.toThrow("name vacio");
  });

  it("sobrevive a un cuerpo de error ilegible", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 500,
      json: async () => { throw new Error("no es json"); },
    }));
    await expect(apiFetch("/x")).rejects.toThrow("HTTP 500");
  });

  it("puede devolver la respuesta cruda para hacer streaming", async () => {
    const raw = jsonResponse({});
    globalThis.fetch = vi.fn(async () => raw);
    expect(await apiFetch("/api/process-video", { json: false })).toBe(raw);
  });
});

describe("api", () => {
  it("normaliza el track_id a texto", async () => {
    await api.setPlayerTeam(7, "team_2");
    const [, init] = globalThis.fetch.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ track_id: "7", team: "team_2" });
  });

  it("envía el instante del frame en el preview", async () => {
    await api.previewFrame(new Blob(["x"]), 12.5);
    const [url] = globalThis.fetch.mock.calls[0];
    expect(url).toContain("timestamp=12.5");
  });

  it("distingue reset suave de completo", async () => {
    await api.reset(true);
    await api.reset();
    expect(globalThis.fetch.mock.calls[0][0]).toContain("soft=true");
    expect(globalThis.fetch.mock.calls[1][0]).toContain("soft=false");
  });
});

describe("wsStreamUrl", () => {
  it("apunta al backend con la sesión codificada", () => {
    expect(wsStreamUrl("mi-sesion")).toMatch(/^ws:\/\/.*\/ws\/stream\?session_id=mi-sesion$/);
  });

  it("usa la sesión de la pestaña por defecto", () => {
    expect(wsStreamUrl()).toContain("session_id=sesion-de-prueba");
  });
});
