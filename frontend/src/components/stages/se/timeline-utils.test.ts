import { describe, it, expect } from "vitest";
import {
  itemsToRegions,
  moveItemTime,
  addItemAt,
  removeItemAt,
  computeSceneBlocks,
  computeSubtitleBlocks,
  clampNoOverlap,
  setItemClip,
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

describe("computeSceneBlocks", () => {
  it("accumulates scene durations into absolute blocks", () => {
    const blocks = computeSceneBlocks([
      { duration: 2, label: "A" },
      { duration: 3 },
    ]);
    expect(blocks[0]).toEqual({ start: 0, end: 2, label: "A" });
    expect(blocks[1]).toEqual({ start: 2, end: 5, label: "S2" });
  });
  it("uses real offsets when provided", () => {
    const blocks = computeSceneBlocks(
      [{ duration: 2 }, { duration: 3 }],
      [0, 2.5],
    );
    expect(blocks[0]).toEqual({ start: 0, end: 2.5, label: "S1" });
    expect(blocks[1].start).toBe(2.5);
  });
});

describe("computeSubtitleBlocks", () => {
  it("offsets line times by scene start", () => {
    const blocks = computeSubtitleBlocks([
      { duration: 2, lines: [{ text: "a", start: 0, end: 1 }] },
      { duration: 3, lines: [{ text: "b", start: 0.5, end: 2 }] },
    ]);
    expect(blocks[0]).toEqual({ start: 0, end: 1, label: "a" });
    expect(blocks[1]).toEqual({ start: 2.5, end: 4, label: "b" });
  });
  it("subtitle uses real offsets when provided", () => {
    const blocks = computeSubtitleBlocks(
      [
        { duration: 2, lines: [{ text: "a", start: 0, end: 1 }] },
        { duration: 3, lines: [{ text: "b", start: 0.5, end: 2 }] },
      ],
      [0, 2.5],
    );
    expect(blocks[1]).toEqual({ start: 3, end: 4.5, label: "b" });
  });
  it("splits into subtitles[] chunks by char ratio", () => {
    const blocks = computeSubtitleBlocks([
      {
        duration: 2,
        lines: [
          {
            text: "abcd",
            start: 0,
            end: 2,
            subtitles: [{ text: "ab" }, { text: "cd" }],
          },
        ],
      },
    ]);
    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toEqual({ start: 0, end: 1, label: "ab" });
    expect(blocks[1]).toEqual({ start: 1, end: 2, label: "cd" });
  });
});

describe("clampNoOverlap", () => {
  it("pushes a moved SE out of an overlapping neighbor", () => {
    // a(width .5) at 0, b(width 1.2) at 2 → move a to 1.9 overlaps b[2,3.2]
    const items = [mk(0, "a"), mk(2, "b")];
    expect(clampNoOverlap(items, tracks, 0, 1.9)).toBe(1.5);
  });
  it("keeps a non-overlapping time", () => {
    const items = [mk(0, "a"), mk(2, "b")];
    expect(clampNoOverlap(items, tracks, 0, 1.0)).toBe(1.0);
  });
});

describe("setItemClip", () => {
  it("sets clip range and clamps to source duration", () => {
    const items = [mk(0, "b")]; // b full 1.2
    const out = setItemClip(items, tracks, 0, 0.2, 0.8);
    expect(out[0]).toMatchObject({ clip_start: 0.2, clip_end: 0.8 });
    const clamped = setItemClip(items, tracks, 0, -1, 5);
    expect(clamped[0].clip_start).toBe(0);
    expect(clamped[0].clip_end).toBe(1.2);
  });
});
