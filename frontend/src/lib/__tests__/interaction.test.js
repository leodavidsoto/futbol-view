import { describe, expect, it } from "vitest";

import { CLICK_SLACK_PX, canvasPointFromEvent, findPlayerAt } from "../interaction.js";

const rect = (extra = {}) => ({ left: 0, top: 0, width: 854, height: 480, ...extra });
const canvas = { width: 854, height: 480 };

describe("canvasPointFromEvent", () => {
  it("sin escalado devuelve el punto tal cual", () => {
    expect(canvasPointFromEvent({ clientX: 100, clientY: 200 }, canvas, rect())).toEqual({ x: 100, y: 200 });
  });

  it("con el canvas mostrado a la mitad, escala x2", () => {
    // El fallo real que esto evita: en una ventana estrecha se seleccionaba el
    // jugador equivocado porque se mezclaban píxeles mostrados con píxeles del
    // búfer de dibujo.
    const punto = canvasPointFromEvent({ clientX: 100, clientY: 100 }, canvas, rect({ width: 427, height: 240 }));
    expect(punto).toEqual({ x: 200, y: 200 });
  });

  it("descuenta el desplazamiento del canvas en la página", () => {
    const punto = canvasPointFromEvent({ clientX: 150, clientY: 250 }, canvas, rect({ left: 50, top: 100 }));
    expect(punto).toEqual({ x: 100, y: 150 });
  });

  it("un canvas de tamaño cero no revienta ni devuelve NaN", () => {
    expect(canvasPointFromEvent({ clientX: 1, clientY: 1 }, canvas, rect({ width: 0, height: 0 }))).toBeNull();
  });

  it("sin canvas devuelve null", () => {
    expect(canvasPointFromEvent({ clientX: 1, clientY: 1 }, null, rect())).toBeNull();
  });
});

describe("findPlayerAt", () => {
  const jugadores = [
    { track_id: 1, center: [100, 100] },
    { track_id: 2, center: [300, 100] },
  ];

  it("encuentra al jugador bajo el cursor", () => {
    expect(findPlayerAt(jugadores, 102, 98, { radius: 22 }).track_id).toBe(1);
  });

  it("elige el más cercano cuando hay dos candidatos", () => {
    const juntos = [{ track_id: 1, center: [100, 100] }, { track_id: 2, center: [115, 100] }];
    expect(findPlayerAt(juntos, 112, 100, { radius: 22 }).track_id).toBe(2);
  });

  it("no hace falta clicar al píxel: hay holgura sobre el radio", () => {
    const justoDentro = 22 + CLICK_SLACK_PX - 1;
    expect(findPlayerAt(jugadores, 100 + justoDentro, 100, { radius: 22 })).not.toBeNull();
  });

  it("fuera del radio más la holgura, no selecciona a nadie", () => {
    const justoFuera = 22 + CLICK_SLACK_PX + 1;
    expect(findPlayerAt(jugadores, 100 + justoFuera, 100, { radius: 22 })).toBeNull();
  });

  it("un círculo arrastrado se coge donde se dejó, no donde lo ve el detector", () => {
    const encontrado = findPlayerAt(jugadores, 500, 400, { radius: 22, posOverrides: { 1: { x: 500, y: 400 } } });
    expect(encontrado?.track_id).toBe(1);
  });

  it("y ya no se coge en su posición original", () => {
    expect(findPlayerAt(jugadores, 100, 100, { radius: 22, posOverrides: { 1: { x: 500, y: 400 } } })).toBeNull();
  });

  it("un radio mayor amplía la zona sensible", () => {
    const lejos = 60;
    expect(findPlayerAt(jugadores, 100 + lejos, 100, { radius: 22 })).toBeNull();
    expect(findPlayerAt(jugadores, 100 + lejos, 100, { radius: 50 })).not.toBeNull();
  });

  it("sin jugadores devuelve null", () => {
    expect(findPlayerAt([], 100, 100, {})).toBeNull();
    expect(findPlayerAt(undefined, 100, 100, {})).toBeNull();
  });
});
