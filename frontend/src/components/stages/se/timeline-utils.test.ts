import { describe, it, expect } from "vitest";
import {
  itemsToRegions,
  moveItemTime,
  addItemAt,
  removeItemAt,
} from "./timeline-utils";
import type { SeItem, SeTrack } from "../../../types";

const tracks: SeTrack[] = [
  {
    id: "a",
    title: "A",
    file: "a.mp3",
    category: "reaction",
    license: "",
    source: "",
    duration_sec: 0.5,
  },
  {
    id: "b",
    title: "B",
    file: "b.mp3",
    category: "sting",
    license: "",
    source: "",
    duration_sec: 1.2,
  },
];

const mk = (time: number, se_id: string): SeItem => ({
  time,
  se_id,
  volume: 0.6,
  source: "auto",
  reason: "",
});

describe("itemsToRegions", () => {
  it("maps time/duration to start/end", () => {
    const r = itemsToRegions([mk(1.0, "a"), mk(3.0, "b")], tracks);
    expect(r[0]).toMatchObject({ idx: 0, start: 1.0, end: 1.5, seId: "a" });
    expect(r[1]).toMatchObject({ idx: 1, start: 3.0, end: 4.2, seId: "b" });
  });
  it("uses a min width for unknown duration", () => {
    const r = itemsToRegions([mk(0, "zzz")], tracks);
    expect(r[0].end).toBeGreaterThan(r[0].start);
  });
});

describe("moveItemTime", () => {
  it("updates time, clamps to >=0, rounds to ms", () => {
    expect(moveItemTime([mk(1.0, "a")], 0, 2.3456)[0].time).toBe(2.346);
    expect(moveItemTime([mk(1.0, "a")], 0, -5)[0].time).toBe(0);
  });
  it("does not touch other items", () => {
    const out = moveItemTime([mk(1, "a"), mk(2, "b")], 0, 5);
    expect(out[1].time).toBe(2);
  });
});

describe("addItemAt / removeItemAt", () => {
  it("adds a manual item rounded/clamped", () => {
    const out = addItemAt([], 1.5012, "a", 0.6);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ time: 1.501, se_id: "a", source: "manual" });
  });
  it("removes by index", () => {
    const out = removeItemAt([mk(1, "a"), mk(2, "b")], 0);
    expect(out).toHaveLength(1);
    expect(out[0].se_id).toBe("b");
  });
});
