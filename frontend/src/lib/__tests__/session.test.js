import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SESSION_STORAGE_KEY,
  createSessionId,
  getSessionId,
  isValidSessionId,
  resetSessionId,
} from "../session.js";

function fakeStorage(initial = {}) {
  const data = { ...initial };
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    removeItem: (k) => { delete data[k]; },
    _data: data,
  };
}

describe("createSessionId", () => {
  it("genera un id aceptado por el backend", () => {
    for (let i = 0; i < 50; i += 1) {
      expect(isValidSessionId(createSessionId())).toBe(true);
    }
  });

  it("no supera los 64 caracteres", () => {
    expect(createSessionId().length).toBeLessThanOrEqual(64);
  });
});

describe("isValidSessionId", () => {
  it.each(["abc", "a-b_c9", "x".repeat(64)])("acepta %s", (id) => {
    expect(isValidSessionId(id)).toBe(true);
  });

  it.each(["", "con espacio", "../etc", "x".repeat(65), null, 42])("rechaza %s", (id) => {
    expect(isValidSessionId(id)).toBe(false);
  });
});

describe("getSessionId", () => {
  let storage;

  beforeEach(() => {
    storage = fakeStorage();
  });

  it("crea y persiste un id la primera vez", () => {
    const id = getSessionId(storage);
    expect(storage.getItem(SESSION_STORAGE_KEY)).toBe(id);
  });

  it("reutiliza el id guardado", () => {
    const first = getSessionId(storage);
    expect(getSessionId(storage)).toBe(first);
  });

  it("descarta un id guardado corrupto", () => {
    storage.setItem(SESSION_STORAGE_KEY, "id invalido con espacios");
    const id = getSessionId(storage);
    expect(isValidSessionId(id)).toBe(true);
    expect(id).not.toContain(" ");
  });

  it("funciona sin almacenamiento (modo privado)", () => {
    expect(isValidSessionId(getSessionId(null))).toBe(true);
    const roto = {
      getItem: () => { throw new Error("bloqueado"); },
      setItem: () => { throw new Error("bloqueado"); },
      removeItem: () => {},
    };
    expect(isValidSessionId(getSessionId(roto))).toBe(true);
  });

  it("no lanza si setItem falla por cuota", () => {
    const lleno = { ...fakeStorage(), setItem: vi.fn(() => { throw new Error("cuota"); }) };
    expect(isValidSessionId(getSessionId(lleno))).toBe(true);
  });
});

describe("resetSessionId", () => {
  it("entrega un id distinto del anterior", () => {
    const storage = fakeStorage();
    const first = getSessionId(storage);
    const second = resetSessionId(storage);
    expect(isValidSessionId(second)).toBe(true);
    expect(storage.getItem(SESSION_STORAGE_KEY)).toBe(second);
    expect(second).not.toBe(first);
  });
});
