import { describe, expect, it } from "vitest";

import {
  SPEED_ZONES,
  fmtDistance,
  fmtSpeed,
  fmtTime,
  hexToRgba,
  pct,
  speedColor,
  speedZone,
  teamColor,
} from "../format.js";

describe("hexToRgba", () => {
  it("convierte hex de 6 dígitos", () => {
    expect(hexToRgba("#00ff88", 0.5)).toBe("rgba(0,255,136,0.5)");
  });

  it("acepta la forma corta de 3 dígitos", () => {
    expect(hexToRgba("#0f8", 1)).toBe("rgba(0,255,136,1)");
  });

  it("no rompe con entradas inválidas", () => {
    expect(hexToRgba("no-es-color", 0.3)).toBe("rgba(0,0,0,0.3)");
    expect(hexToRgba(undefined, 1)).toBe("rgba(0,0,0,1)");
    expect(hexToRgba("#zzzzzz", 1)).toBe("rgba(0,0,0,1)");
  });
});

describe("fmtTime", () => {
  it.each([
    [0, "0:00"],
    [9, "0:09"],
    [65, "1:05"],
    [600, "10:00"],
    [3661, "1:01:01"],
  ])("%s s → %s", (input, expected) => {
    expect(fmtTime(input)).toBe(expected);
  });

  it("trata valores ausentes o negativos como cero", () => {
    expect(fmtTime(undefined)).toBe("0:00");
    expect(fmtTime(-5)).toBe("0:00");
    expect(fmtTime(NaN)).toBe("0:00");
  });
});

describe("fmtDistance", () => {
  it("usa metros por debajo del kilómetro", () => {
    expect(fmtDistance(845.4)).toBe("845 m");
  });

  it("cambia a kilómetros a partir de 1000 m", () => {
    expect(fmtDistance(1240)).toBe("1.24 km");
  });

  it("tolera basura", () => {
    expect(fmtDistance(undefined)).toBe("0 m");
  });
});

describe("velocidad", () => {
  it("formatea con un decimal", () => {
    expect(fmtSpeed(23.456)).toBe("23.5 km/h");
  });

  it.each([
    [3, "caminando"],
    [10, "trote"],
    [17, "carrera"],
    [23, "alta_intensidad"],
    [31, "sprint"],
  ])("%s km/h está en la zona %s", (kmh, zona) => {
    expect(speedZone(kmh).name).toBe(zona);
  });

  it("las zonas cubren todo el rango sin huecos", () => {
    for (let i = 0; i < SPEED_ZONES.length - 1; i += 1) {
      expect(SPEED_ZONES[i].max).toBe(SPEED_ZONES[i + 1].min);
    }
    expect(SPEED_ZONES[0].min).toBe(0);
    expect(SPEED_ZONES.at(-1).max).toBe(Infinity);
  });

  it("da un color por zona", () => {
    expect(speedColor(30)).toBe(SPEED_ZONES.at(-1).color);
    expect(speedColor(0)).toBe(SPEED_ZONES[0].color);
  });
});

describe("teamColor", () => {
  it("resuelve los equipos conocidos", () => {
    expect(teamColor("team_1")).toBe("#00ff88");
    expect(teamColor("team_2")).toBe("#ff3355");
  });

  it("usa el color neutro para lo demás", () => {
    expect(teamColor("unknown")).toBe("#aaaaaa");
    expect(teamColor(undefined)).toBe("#aaaaaa");
  });
});

describe("pct", () => {
  it("acota al rango 0-100", () => {
    expect(pct(-20)).toBe(0);
    expect(pct(150)).toBe(100);
    expect(pct(42.5)).toBe(42.5);
    expect(pct("nada")).toBe(0);
  });
});
