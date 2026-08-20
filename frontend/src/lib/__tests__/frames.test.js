import { describe, expect, it, vi } from "vitest";

import {
  findFrameAtTime,
  findFrameIndexAtTime,
  frameTime,
  parseNdjsonChunk,
  summarizeFrame,
} from "../frames.js";

const frames = Array.from({ length: 100 }, (_, i) => ({ frame: i, video_time: i * 0.12 }));

describe("frameTime", () => {
  it("prefiere video_time y cae a t", () => {
    expect(frameTime({ video_time: 3, t: 9 })).toBe(3);
    expect(frameTime({ t: 9 })).toBe(9);
    expect(frameTime({})).toBe(0);
    expect(frameTime(null)).toBe(0);
  });
});

describe("findFrameIndexAtTime", () => {
  it("encuentra el frame exacto", () => {
    expect(findFrameIndexAtTime(frames, 1.2)).toBe(10);
  });

  it("elige el más cercano cuando cae entre dos", () => {
    expect(findFrameIndexAtTime(frames, 1.19)).toBe(10);
    expect(findFrameIndexAtTime(frames, 1.14)).toBe(9);
  });

  it("acota en los extremos", () => {
    expect(findFrameIndexAtTime(frames, -10)).toBe(0);
    expect(findFrameIndexAtTime(frames, 9999)).toBe(frames.length - 1);
  });

  it("devuelve -1 sin frames", () => {
    expect(findFrameIndexAtTime([], 1)).toBe(-1);
    expect(findFrameIndexAtTime(null, 1)).toBe(-1);
    expect(findFrameAtTime([], 1)).toBeNull();
  });

  it("coincide con la búsqueda lineal para cualquier instante", () => {
    const lineal = (time) =>
      frames.reduce(
        (best, f, i) =>
          Math.abs(frameTime(f) - time) < Math.abs(frameTime(frames[best]) - time) ? i : best,
        0,
      );
    for (const t of [0, 0.05, 0.061, 3.14, 6.0, 11.87, 12.5]) {
      expect(findFrameIndexAtTime(frames, t)).toBe(lineal(t));
    }
  });

  it("devuelve el objeto frame", () => {
    expect(findFrameAtTime(frames, 2.4).frame).toBe(20);
  });
});

describe("parseNdjsonChunk", () => {
  it("separa las líneas completas y conserva el resto", () => {
    const { frames: parsed, rest } = parseNdjsonChunk('{"a":1}\n{"a":2}\n{"a":3');
    expect(parsed).toEqual([{ a: 1 }, { a: 2 }]);
    expect(rest).toBe('{"a":3');
  });

  it("ignora líneas vacías", () => {
    const { frames: parsed } = parseNdjsonChunk('{"a":1}\n\n\n');
    expect(parsed).toEqual([{ a: 1 }]);
  });

  it("avisa de las líneas corruptas sin abortar", () => {
    const onError = vi.fn();
    const { frames: parsed } = parseNdjsonChunk('{"a":1}\nroto\n{"a":2}\n', onError);
    expect(parsed).toEqual([{ a: 1 }, { a: 2 }]);
    expect(onError).toHaveBeenCalledTimes(1);
  });
});

describe("summarizeFrame", () => {
  const frame = {
    players: [
      { team: "team_1", speed_kmh: 12, total_dist_m: 300, sprints: 1 },
      { team: "team_1", speed_kmh: 28.5, total_dist_m: 250, sprints: 3 },
      { team: "team_2", speed_kmh: 5, total_dist_m: 100, sprints: 0 },
    ],
    possession: { share: { team_1: 60, team_2: 40 } },
  };

  it("agrega los datos del frame", () => {
    expect(summarizeFrame(frame)).toEqual({
      players: 3,
      team1: 2,
      team2: 1,
      topSpeed: 28.5,
      totalDistance: 650,
      sprints: 4,
      possession: { team_1: 60, team_2: 40 },
    });
  });

  it("acepta el formato antiguo de posesión", () => {
    const legacy = { players: [], ball: { possession_pct: { team_1: 55, team_2: 45 } } };
    expect(summarizeFrame(legacy).possession).toEqual({ team_1: 55, team_2: 45 });
  });

  it("no rompe sin datos", () => {
    expect(summarizeFrame(null).players).toBe(0);
    expect(summarizeFrame(undefined).possession).toEqual({ team_1: 0, team_2: 0 });
  });
});
