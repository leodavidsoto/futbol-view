import { describe, expect, it } from "vitest";

import {
  COLUMNS,
  bandColor,
  bandShares,
  byTeam,
  cell,
  confidenceStyle,
  fmt,
  fmtDropoff,
  fmtDuration,
  fmtFragmentation,
  headline,
  isActionable,
  possessionShare,
  statusStyle,
} from "../model.js";

const panel = (over = {}) => ({
  quality: { confidence: "alta", warnings: [] },
  attention: [],
  players: [{ track_id: 1, name: "J1", team: "team_1" }],
  ...over,
});

describe("titular del panel", () => {
  it("antepone la advertencia a la conclusión cuando los datos no se sostienen", () => {
    // Enseñar «cambia a Pérez» encima de datos que no valen es exactamente
    // cómo se toma una decisión mala con un panel bonito.
    const resultado = headline(panel({
      quality: {
        confidence: "baja",
        warnings: [{ level: "critico", code: "fragmentacion", message: "3,1 identidades por jugador." }],
      },
      attention: [{ name: "Pérez", status: "cambio" }],
    }));
    expect(resultado.tone).toBe("bad");
    expect(resultado.text).toContain("identidades");
    expect(resultado.text).not.toContain("Pérez");
  });

  it("nombra al jugador cuando hay uno solo", () => {
    const resultado = headline(panel({ attention: [{ name: "Pérez", status: "cambio" }] }));
    expect(resultado.text).toContain("Pérez");
    expect(resultado.tone).toBe("bad");
  });

  it("cuenta cuando hay varios", () => {
    const resultado = headline(panel({
      attention: [
        { name: "Pérez", status: "cambio" },
        { name: "Gómez", status: "cambio" },
      ],
    }));
    expect(resultado.text).toContain("2 jugadores");
  });

  it("distingue vigilar de cambiar", () => {
    const resultado = headline(panel({ attention: [{ name: "Pérez", status: "vigilar" }] }));
    expect(resultado.tone).toBe("warn");
  });

  it("dice que todo está en orden sólo si de verdad hay jugadores", () => {
    expect(headline(panel()).tone).toBe("good");
    expect(headline(panel({ players: [] })).tone).toBe("neutral");
  });

  it("no revienta sin datos", () => {
    expect(headline(undefined).tone).toBe("neutral");
    expect(headline({}).tone).toBe("neutral");
  });
});

describe("confianza", () => {
  it("el semáforo se tapa cuando los datos no se sostienen", () => {
    expect(isActionable({ confidence: "alta" })).toBe(true);
    expect(isActionable({ confidence: "media" })).toBe(true);
    expect(isActionable({ confidence: "baja" })).toBe(false);
    expect(isActionable(null)).toBe(false);
  });

  it("la confianza baja se dice sin rodeos", () => {
    expect(confidenceStyle("baja").label).toMatch(/no decidas/i);
  });

  it("una confianza que no conoce no se inventa un color de aprobación", () => {
    expect(confidenceStyle("dorada").label).toBe("Sin evaluar");
  });
});

describe("estados", () => {
  it("cada estado tiene su color", () => {
    expect(statusStyle("cambio").color).not.toBe(statusStyle("ok").color);
    expect(statusStyle("vigilar").color).not.toBe(statusStyle("ok").color);
  });

  it("un estado nuevo del backend no se pinta como correcto", () => {
    // Que un estado desconocido salga verde sería lo peor posible.
    expect(statusStyle("agotado").color).not.toBe(statusStyle("ok").color);
  });
});

describe("bandas de intensidad", () => {
  it("reparte en porcentajes que suman 100", () => {
    const partes = bandShares({ caminando: 300, trote: 500, sprint: 200 });
    expect(partes).toHaveLength(3);
    expect(partes.reduce((s, p) => s + p.pct, 0)).toBeCloseTo(100);
  });

  it("un jugador que no recorrió nada no dibuja barra", () => {
    // Cuatro segmentos a cero se pintan como una barra llena de un color
    // arbitrario, que dice algo falso.
    expect(bandShares({ caminando: 0, trote: 0 })).toEqual([]);
    expect(bandShares(null)).toEqual([]);
  });

  it("las bandas se ordenan por color de menos a más intensa", () => {
    expect(bandColor("sprint")).not.toBe(bandColor("caminando"));
    expect(bandColor("banda_que_no_existe")).toBeTruthy();
  });
});

describe("agrupación por equipo", () => {
  it("agrupa y deja los equipos en orden estable", () => {
    const grupos = byTeam([
      { name: "a", team: "team_2" },
      { name: "b", team: "team_1" },
      { name: "c", team: "team_2" },
    ]);
    expect(grupos.map((g) => g.team)).toEqual(["team_1", "team_2"]);
    expect(grupos[1].players).toHaveLength(2);
  });

  it("un jugador sin equipo no se pierde", () => {
    const grupos = byTeam([{ name: "a" }]);
    expect(grupos[0].team).toBe("unknown");
  });

  it("sin jugadores devuelve una lista vacía", () => {
    expect(byTeam(undefined)).toEqual([]);
  });
});

describe("formato", () => {
  it("distingue «no se sabe» de cero", () => {
    // Es la mitad de los errores de lectura de un panel.
    expect(fmt(null)).toBe("—");
    expect(fmt(undefined)).toBe("—");
    expect(fmt(0)).toBe("0");
  });

  it("no inventa decimales", () => {
    expect(fmt(1234.567, { unit: "m" })).toBe("1235 m");
    expect(fmt(28.34, { unit: "km/h", decimals: 1 })).toBe("28.3 km/h");
  });

  it("la caída lleva signo explícito y «—» si no hay referencia", () => {
    expect(fmtDropoff(-25.4)).toBe("-25 %");
    expect(fmtDropoff(4.2)).toBe("+4 %");
    expect(fmtDropoff(null)).toBe("—");
  });
});

describe("columnas de la tabla", () => {
  it("cabeceras y valores salen de la misma tabla", () => {
    // Cuando eran dos listas paralelas, añadir una columna en un sitio y no en
    // el otro corría todos los valores una casilla a la derecha.
    const fila = {
      name: "J1", minutes: 62.4, dist_m: 8123.6, dist_m_per_min: 130.2,
      hi_m_per_min: 41.7, sprints: 9, top_speed_kmh: 29.44,
      accelerations: 18, decelerations: 21, dropoff_pct: -12.3,
    };
    expect(COLUMNS.map((c) => cell(c, fila))).toEqual([
      "J1", "62", "8124 m", "130", "42 m/min", "9", "29.4 km/h", "18", "21", "-12 %",
    ]);
  });

  it("una fila incompleta no rompe la tabla", () => {
    expect(COLUMNS.map((c) => cell(c, { name: "J2" }))).toContain("—");
  });
});

describe("posesión", () => {
  it("lee el reparto de donde está de verdad, no de la raíz", () => {
    // Este objeto es la forma que devuelve `PossessionTracker.snapshot()` del
    // backend. El panel leía `possession.team_1`, que no existe: la posesión
    // salía «— / —» en pantalla mientras el backend la calculaba bien.
    const snapshot = {
      holder: "team_1",
      changes: 12,
      interruptions: 4,
      seconds: { team_1: 800.0, team_2: 700.0, none: 300.0 },
      share: { team_1: 53.3, team_2: 46.7 },
      percentages: { team_1: 44.4, team_2: 38.9, none: 16.7 },
    };
    expect(possessionShare(snapshot)).toEqual({ team_1: 53.3, team_2: 46.7 });
  });

  it("sin posesión devuelve nulos y no ceros", () => {
    expect(possessionShare(undefined)).toEqual({ team_1: null, team_2: null });
    expect(possessionShare({})).toEqual({ team_1: null, team_2: null });
  });
});

describe("duración y fragmentación", () => {
  it("por debajo de un minuto se dan segundos", () => {
    // «0 min analizados» sobre un clip de diez segundos parece que falló algo.
    expect(fmtDuration(0.17)).toBe("10 s");
    expect(fmtDuration(3.4)).toBe("3.4 min");
    expect(fmtDuration(92)).toBe("92 min");
    expect(fmtDuration(null)).toBe("—");
  });

  it("la fragmentación concuerda en número", () => {
    expect(fmtFragmentation(1)).toBe("1,0 identidad por jugador");
    expect(fmtFragmentation(2.32)).toBe("2,3 identidades por jugador");
    expect(fmtFragmentation(null)).toBeNull();
  });
});
