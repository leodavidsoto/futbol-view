/**
 * El dibujo del overlay, probado sin navegador.
 *
 * El contexto 2D se sustituye por un espía que apunta cada llamada. No se
 * comprueba que los píxeles queden bonitos —eso no lo puede decir una prueba—
 * sino las decisiones: qué capa se dibuja, con qué color, en qué coordenada, y
 * sobre todo las que dependen de datos del backend, que son las que se rompen
 * cuando cambia el contrato.
 */

import { describe, expect, it, vi } from "vitest";

import { TEAM_COLORS, teamColor } from "../../lib/format.js";
import {
  CALIB_LABELS,
  drawBall,
  drawBallTrail,
  drawBoundingBoxes,
  drawCalibration,
  drawMinimap,
  drawPlayers,
  drawPossessionBar,
  drawScene,
  effectiveCenter,
  effectiveTeam,
  projectToMinimap,
} from "../scene.js";

/** Contexto 2D de mentira: apunta llamadas y asignaciones de estilo. */
function fakeCtx() {
  const calls = [];
  const registrar = (nombre) => (...args) => calls.push({ fn: nombre, args });
  const ctx = {
    calls,
    fillStyle: null,
    strokeStyle: null,
    lineWidth: 0,
    font: "",
    textAlign: "",
    textBaseline: "",
    globalAlpha: 1,
    shadowColor: null,
    shadowBlur: 0,
    clearRect: registrar("clearRect"),
    fillRect: registrar("fillRect"),
    strokeRect: registrar("strokeRect"),
    beginPath: registrar("beginPath"),
    arc: registrar("arc"),
    moveTo: registrar("moveTo"),
    lineTo: registrar("lineTo"),
    stroke: registrar("stroke"),
    roundRect: registrar("roundRect"),
    setLineDash: registrar("setLineDash"),
    fillText: registrar("fillText"),
    measureText: vi.fn(() => ({ width: 40 })),
  };
  // `fill` y `fillRect` tienen que capturar el color vigente en ese momento:
  // el estilo es mutable y mirarlo al final daría siempre el último.
  ctx.fill = (...args) => calls.push({ fn: "fill", args, fillStyle: ctx.fillStyle });
  const fillRectOriginal = ctx.fillRect;
  ctx.fillRect = (...args) => {
    fillRectOriginal(...args);
    calls[calls.length - 1].fillStyle = ctx.fillStyle;
  };
  const strokeOriginal = ctx.stroke;
  ctx.stroke = (...args) => {
    strokeOriginal(...args);
    calls[calls.length - 1].strokeStyle = ctx.strokeStyle;
  };
  return ctx;
}

const llamadas = (ctx, fn) => ctx.calls.filter((c) => c.fn === fn);
const canvas = { width: 854, height: 480 };

const jugador = (extra = {}) => ({
  track_id: 1,
  team: "team_1",
  name: "#1",
  center: [100, 200],
  bbox: [88, 170, 112, 230],
  speed_kmh: 12.5,
  total_dist_m: 340.2,
  trail: [{ x: 90, y: 190 }, { x: 95, y: 195 }, { x: 100, y: 200 }],
  ...extra,
});

// ── Resolución de equipo y posición ─────────────────────────────────────
describe("equipo y posición efectivos", () => {
  it("la corrección manual manda sobre la del clasificador", () => {
    expect(effectiveTeam(jugador(), { 1: "team_2" })).toBe("team_2");
  });

  it("sin corrección se usa el equipo del backend", () => {
    expect(effectiveTeam(jugador(), {})).toBe("team_1");
  });

  it("un círculo arrastrado a mano manda sobre la posición detectada", () => {
    expect(effectiveCenter(jugador(), { 1: { x: 7, y: 9 } })).toEqual([7, 9]);
  });

  it("sin arrastre se usa el centro detectado", () => {
    expect(effectiveCenter(jugador(), {})).toEqual([100, 200]);
  });
});

// ── Barra de posesión ───────────────────────────────────────────────────
describe("barra de posesión", () => {
  it("reparte el ancho en proporción a la posesión", () => {
    const ctx = fakeCtx();
    drawPossessionBar(ctx, { ball: { possession_pct: { team_1: 75, team_2: 25 } } }, { width: 800 });
    const [primera, segunda] = llamadas(ctx, "fillRect");
    expect(primera.args).toEqual([0, 0, 600, 5]);
    expect(primera.fillStyle).toBe(TEAM_COLORS.team_1);
    expect(segunda.args).toEqual([600, 0, 200, 5]);
    expect(segunda.fillStyle).toBe(TEAM_COLORS.team_2);
  });

  it("con posesión cero no divide por cero", () => {
    const ctx = fakeCtx();
    drawPossessionBar(ctx, { ball: { possession_pct: { team_1: 0, team_2: 0 } } }, { width: 800 });
    llamadas(ctx, "fillRect").forEach((c) => c.args.forEach((v) => expect(Number.isFinite(v)).toBe(true)));
  });

  it("sin datos de posesión no dibuja nada", () => {
    const ctx = fakeCtx();
    drawPossessionBar(ctx, { ball: {} }, { width: 800 });
    expect(ctx.calls).toHaveLength(0);
  });
});

// ── Jugadores ───────────────────────────────────────────────────────────
describe("jugadores", () => {
  it("usa el color del equipo corregido a mano", () => {
    const ctx = fakeCtx();
    drawPlayers(ctx, { players: [jugador()] }, { overrides: { 1: "team_2" } });
    const pintados = llamadas(ctx, "fill").map((c) => c.fillStyle);
    expect(pintados.some((c) => c === teamColor("team_2"))).toBe(true);
  });

  it("dibuja el nombre corregido, no el del backend", () => {
    const ctx = fakeCtx();
    drawPlayers(ctx, { players: [jugador()] }, { playerNames: { 1: "Iniesta" }, showNames: true });
    expect(llamadas(ctx, "fillText").map((c) => c.args[0])).toContain("Iniesta");
  });

  it("no dibuja la velocidad de un jugador parado", () => {
    const ctx = fakeCtx();
    drawPlayers(ctx, { players: [jugador({ speed_kmh: 0.2 })] }, { showSpeed: true });
    expect(llamadas(ctx, "fillText").map((c) => c.args[0]).join(" ")).not.toContain("km/h");
  });

  it("baja la distancia una línea si la velocidad ya ocupa la de debajo", () => {
    const conVelocidad = fakeCtx();
    drawPlayers(conVelocidad, { players: [jugador()] }, { showSpeed: true, showDistance: true, circleRadius: 20 });
    const sinVelocidad = fakeCtx();
    drawPlayers(sinVelocidad, { players: [jugador({ speed_kmh: 0 })] }, { showSpeed: true, showDistance: true, circleRadius: 20 });

    const yDe = (ctx) => llamadas(ctx, "fillText").find((c) => String(c.args[0]).endsWith(" m")).args[2];
    expect(yDe(conVelocidad)).toBeGreaterThan(yDe(sinVelocidad));
  });

  it("marca con línea discontinua el círculo que se está arrastrando", () => {
    const ctx = fakeCtx();
    drawPlayers(ctx, { players: [jugador()] }, { draggingTrackId: 1 });
    expect(llamadas(ctx, "setLineDash").map((c) => c.args[0])).toEqual([[5, 3], []]);
  });

  it("no deja la línea discontinua puesta para lo que se dibuje después", () => {
    const ctx = fakeCtx();
    drawPlayers(ctx, { players: [jugador()] }, { draggingTrackId: 1 });
    expect(llamadas(ctx, "setLineDash").at(-1).args[0]).toEqual([]);
  });

  it("recorta el rastro a la longitud pedida", () => {
    const largo = Array.from({ length: 50 }, (_, i) => ({ x: i, y: i }));
    const ctx = fakeCtx();
    drawPlayers(ctx, { players: [jugador({ trail: largo })] }, { showTrails: true, trailLength: 5, showNames: false });
    expect(llamadas(ctx, "arc").length).toBe(2 + 5);   // círculo, punto central y 5 del rastro
  });

  it("sin jugadores no falla", () => {
    const ctx = fakeCtx();
    expect(() => drawPlayers(ctx, {}, {})).not.toThrow();
  });
});

// ── Pelota y cajas ──────────────────────────────────────────────────────
describe("pelota y cajas", () => {
  it("dibuja la pelota en su centro", () => {
    const ctx = fakeCtx();
    drawBall(ctx, { ball: { center: [400, 300] } });
    expect(llamadas(ctx, "arc")[0].args.slice(0, 2)).toEqual([400, 300]);
  });

  it("sin pelota no dibuja nada", () => {
    const ctx = fakeCtx();
    drawBall(ctx, {});
    expect(ctx.calls).toHaveLength(0);
  });

  it("la caja se dibuja como origen y tamaño, no como esquinas", () => {
    const ctx = fakeCtx();
    drawBoundingBoxes(ctx, { players: [jugador()] }, { overrides: {} });
    expect(llamadas(ctx, "strokeRect")[0].args).toEqual([88, 170, 24, 60]);
  });

  it("un rastro de pelota de un solo punto no se dibuja", () => {
    const ctx = fakeCtx();
    drawBallTrail(ctx, { ball: { trail: [{ x: 1, y: 1 }] } }, { trailLength: 20 });
    expect(ctx.calls).toHaveLength(0);
  });
});

// ── Mini-mapa ───────────────────────────────────────────────────────────
describe("mini-mapa", () => {
  const box = { x: 0, y: 0, width: 160, height: 96 };

  it("con calibración proyecta metros de campo", () => {
    // Centro del campo (52.5, 34) → centro del mini-mapa.
    expect(projectToMinimap([52.5, 34], { useWorld: true, box, frame: canvas })).toEqual([80, 48]);
  });

  it("sin calibración proyecta la proporción del frame", () => {
    expect(projectToMinimap([427, 240], { useWorld: false, box, frame: canvas })).toEqual([80, 48]);
  });

  it("un jugador sin world_pos no se proyecta como si tuviera metros", () => {
    // El bug que esto evita: mezclar los dos sistemas pone a unos en su sitio
    // y a otros en una esquina.
    const ctx = fakeCtx();
    drawMinimap(
      ctx,
      { players: [jugador({ world_pos: [52.5, 34] }), jugador({ track_id: 2, center: [427, 240] })] },
      { ...canvas, overrides: {}, posOverrides: {} },
    );
    const puntos = llamadas(ctx, "arc").slice(1);   // el primero es el círculo central
    expect(puntos).toHaveLength(2);
    const [a, b] = puntos.map((c) => c.args.slice(0, 2));
    expect(a[0]).toBeCloseTo(b[0], 0);
    expect(a[1]).toBeCloseTo(b[1], 0);
  });

  it("sin jugadores no se dibuja", () => {
    const ctx = fakeCtx();
    drawMinimap(ctx, { players: [] }, { ...canvas });
    expect(ctx.calls).toHaveLength(0);
  });
});

// ── Calibración ─────────────────────────────────────────────────────────
describe("calibración", () => {
  it("etiqueta las esquinas en orden", () => {
    const ctx = fakeCtx();
    drawCalibration(ctx, { calibrating: false, calibPoints: [{ x: 1, y: 1 }, { x: 2, y: 2 }] });
    expect(llamadas(ctx, "fillText").map((c) => c.args[0])).toEqual([CALIB_LABELS[0], CALIB_LABELS[1]]);
  });

  it("mientras se calibra dice cuál es la siguiente esquina", () => {
    const ctx = fakeCtx();
    drawCalibration(ctx, { calibrating: true, calibPoints: [{ x: 1, y: 1 }] });
    expect(llamadas(ctx, "fillText").at(-1).args[0]).toBe("Click → TR (1/4)");
  });

  it("con las cuatro puestas ya no pide más", () => {
    const ctx = fakeCtx();
    const cuatro = [1, 2, 3, 4].map((n) => ({ x: n, y: n }));
    drawCalibration(ctx, { calibrating: true, calibPoints: cuatro });
    expect(llamadas(ctx, "fillText").at(-1).args[0]).toBe("Click → undefined (4/4)");
  });
});

// ── Orquestación ────────────────────────────────────────────────────────
describe("drawScene", () => {
  const datos = { players: [jugador()], ball: { center: [400, 300], possession_pct: { team_1: 60, team_2: 40 } } };

  it("limpia el canvas antes de dibujar", () => {
    const ctx = fakeCtx();
    drawScene(ctx, canvas, datos, {});
    expect(ctx.calls[0].fn).toBe("clearRect");
  });

  it("sin datos no dibuja y lo dice", () => {
    const ctx = fakeCtx();
    expect(drawScene(ctx, canvas, null, {})).toBe(false);
    expect(ctx.calls).toHaveLength(0);
  });

  it("las capas opcionales están apagadas por defecto", () => {
    const ctx = fakeCtx();
    drawScene(ctx, canvas, datos, {});
    // Los nombres SÍ vienen activados por defecto en `drawPlayers`, igual que en
    // la app: lo que no debe aparecer sin pedirlo es la barra y el mini-mapa.
    const enY0 = llamadas(ctx, "fillRect").filter((c) => c.args[1] === 0 && c.args[3] === 5);
    expect(enY0).toHaveLength(0);
    expect(llamadas(ctx, "roundRect")).toHaveLength(0);
  });

  it("la barra de posesión sólo aparece si se pide", () => {
    const ctx = fakeCtx();
    drawScene(ctx, canvas, datos, { showPossessionBar: true });
    expect(llamadas(ctx, "fillRect").length).toBeGreaterThan(0);
  });

  it("el mini-mapa se dibuja después de los jugadores, para quedar encima", () => {
    const ctx = fakeCtx();
    drawScene(ctx, canvas, datos, { showMiniMap: true });
    const iMinimapa = ctx.calls.findIndex((c) => c.fn === "roundRect");
    const iJugador = ctx.calls.findIndex((c) => c.fn === "arc");
    expect(iMinimapa).toBeGreaterThan(iJugador);
  });
});
