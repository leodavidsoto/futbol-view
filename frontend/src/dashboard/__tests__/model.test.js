import { describe, expect, it } from "vitest";

import {
  BAND_ORDER,
  COLLECTIVE_TILES,
  COLUMNS,
  HEAT_RAMP,
  bandColor,
  bandLabel,
  bandShares,
  byTeam,
  cell,
  collectiveTeams,
  confidenceStyle,
  fmt,
  fmtDropoff,
  fmtDuration,
  fmtFragmentation,
  hasCollective,
  headline,
  heatColor,
  isActionable,
  possessionShare,
  series,
  statusStyle,
  teamColor,
  teamLabel,
  zoneGrid,
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

describe("rampa de bandas", () => {
  it("es ordinal: la claridad crece con la intensidad", () => {
    // Es lo único que hace que una barra apilada se lea como una escala, y lo
    // que la versión anterior no cumplía: el rojo del sprint era más oscuro
    // que el amarillo que iba antes.
    const luz = (hex) => {
      const n = parseInt(hex.slice(1), 16);
      const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => v / 255);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const claridades = BAND_ORDER.map((b) => luz(bandColor(b)));
    for (let i = 1; i < claridades.length; i += 1) {
      expect(claridades[i]).toBeGreaterThan(claridades[i - 1]);
    }
  });

  it("cada banda tiene nombre legible", () => {
    // `muy_alta_velocidad` en pantalla es un descuido, no un dato.
    for (const banda of BAND_ORDER) {
      expect(bandLabel(banda)).not.toContain("_");
    }
  });

  it("una banda que el backend añada mañana no revienta la leyenda", () => {
    expect(bandColor("banda_nueva")).toBeTruthy();
    expect(bandLabel("banda_nueva")).toBe("banda_nueva");
  });
});

describe("equipos", () => {
  it("los dos equipos tienen colores distintos y nombre", () => {
    expect(teamColor("team_1")).not.toBe(teamColor("team_2"));
    expect(teamLabel("team_1")).toBe("Equipo 1");
    expect(teamLabel("unknown")).toBe("Sin asignar");
  });

  it("un equipo desconocido no se pinta como uno de los dos", () => {
    expect(teamColor("team_9")).toBe(teamColor("unknown"));
  });
});

describe("mapa de calor", () => {
  it("se normaliza al máximo de la rejilla y no a 100", () => {
    // En quince zonas ninguna pasa del 20 %: contra una escala fija saldría
    // todo del mismo color oscuro y el mapa no diría nada.
    expect(heatColor(18, 18)).toBe(HEAT_RAMP[HEAT_RAMP.length - 1]);
    expect(heatColor(2, 18)).toBe(HEAT_RAMP[0]);
  });

  it("una zona sin tiempo no se pinta", () => {
    expect(heatColor(0, 18)).toBe("transparent");
    expect(heatColor(5, 0)).toBe("transparent");
  });

  it("la rampa es de un solo tono y va de oscuro a claro", () => {
    const luz = (hex) => {
      const n = parseInt(hex.slice(1), 16);
      return ((n >> 16) & 255) + ((n >> 8) & 255) + (n & 255);
    };
    const claridades = HEAT_RAMP.map(luz);
    for (let i = 1; i < claridades.length; i += 1) {
      expect(claridades[i]).toBeGreaterThan(claridades[i - 1]);
    }
  });
});

describe("rejilla de zonas", () => {
  const ocupacion = {
    total_s: 100,
    zones: {
      "tercio_1|banda_1": { seconds: 40, pct: 40 },
      "tercio_1|centro": { seconds: 10, pct: 10 },
      "tercio_2|banda_1": { seconds: 0, pct: 0 },
      "tercio_2|centro": { seconds: 50, pct: 50 },
    },
  };

  it("saca los tercios y los carriles del nombre de la zona", () => {
    const rejilla = zoneGrid(ocupacion);
    expect(rejilla.thirds).toEqual(["tercio_1", "tercio_2"]);
    expect(rejilla.corridors).toEqual(["banda_1", "centro"]);
    expect(rejilla.max).toBe(50);
  });

  it("una zona que no está se lee como cero y no revienta", () => {
    expect(zoneGrid(ocupacion).cell("tercio_9", "centro")).toEqual({ seconds: 0, pct: 0 });
  });

  it("sin ocupación no hay rejilla", () => {
    expect(zoneGrid(null)).toBeNull();
    expect(zoneGrid({})).toBeNull();
  });
});

describe("series temporales", () => {
  const timeline = [
    { from_s: 0, width_m: 30, samples: 12 },
    { from_s: 60, width_m: 0, samples: 0 },
    { from_s: 120, width_m: 26, samples: 9 },
  ];

  it("un bloque sin muestras no se dibuja a cero", () => {
    // Una línea que baja a cero y vuelve se lee como un colapso que no ocurrió:
    // ese minuto no se vio al equipo, no es que su amplitud fuera cero.
    const puntos = series(timeline, "width_m");
    expect(puntos).toHaveLength(2);
    expect(puntos.map((p) => p.y)).toEqual([30, 26]);
  });

  it("el eje x va en minutos", () => {
    expect(series(timeline, "width_m")[1].x).toBe(2);
  });

  it("sin línea de tiempo devuelve una serie vacía", () => {
    expect(series(undefined, "width_m")).toEqual([]);
  });
});

describe("¿hay sección colectiva?", () => {
  it("sin calibrar no la hay, y por eso no debe haber pestaña", () => {
    expect(hasCollective({ collective: null })).toBe(false);
    expect(hasCollective({})).toBe(false);
  });

  it("un equipo visto pero sin forma medible tampoco la enciende", () => {
    // Se le vio ocupar espacio, pero con tres jugadores «amplitud» no existe.
    expect(hasCollective({ collective: { teams: { team_1: { shape: {} } } } })).toBe(false);
  });

  it("con forma medida, sí", () => {
    const panel = { collective: { teams: { team_1: { shape: { width_m: { avg: 30 } } } } } };
    expect(hasCollective(panel)).toBe(true);
  });

  it("los equipos salen en orden estable", () => {
    const panel = { teams: { team_2: {}, team_1: {} } };
    expect(collectiveTeams(panel)).toEqual(["team_1", "team_2"]);
    expect(collectiveTeams(null)).toEqual([]);
  });
});

describe("las fichas colectivas", () => {
  it("usan la longitud recortada, no la completa", () => {
    // La completa la marca el portero, treinta metros por detrás de la línea.
    const claves = COLLECTIVE_TILES.map((t) => t.key);
    expect(claves).toContain("length_trimmed_m");
    expect(claves).not.toContain("length_m");
  });

  it("cada ficha dice qué es, no sólo cómo se llama", () => {
    for (const ficha of COLLECTIVE_TILES) {
      expect(ficha.help.length).toBeGreaterThan(10);
      expect(ficha.unit).toBeTruthy();
    }
  });
});
