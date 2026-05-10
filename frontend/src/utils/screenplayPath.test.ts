import { describe, expect, it } from "vitest";
import type { Screenplay } from "../types";
import { replaceChunk, replaceLine, replaceScene } from "./screenplayPath";

function makeSp(): Screenplay {
  return {
    caption: "x",
    scenes: [
      {
        duration: 2,
        background_prompt: "a",
        lines: [
          {
            text: "first",
            start: 0,
            end: 1,
            subtitles: [
              { text: "f1", _uid: "u1" },
              { text: "f2", _uid: "u2" },
            ],
          },
          { text: "second", start: 1, end: 2 },
        ],
      },
      {
        duration: 1,
        background_prompt: "b",
        lines: [{ text: "third", start: 0, end: 1 }],
      },
    ],
  } as unknown as Screenplay;
}

describe("replaceScene", () => {
  it("returns a new screenplay reference", () => {
    const sp = makeSp();
    const next = replaceScene(sp, 0, (s) => ({ ...s, duration: 99 }));
    expect(next).not.toBe(sp);
    expect(next.scenes[0].duration).toBe(99);
  });

  it("preserves untouched sibling scenes by reference (= no deep clone)", () => {
    const sp = makeSp();
    const next = replaceScene(sp, 0, (s) => ({ ...s, duration: 99 }));
    expect(next.scenes[1]).toBe(sp.scenes[1]);
  });

  it("creates a new scenes array (= setState detects change)", () => {
    const sp = makeSp();
    const next = replaceScene(sp, 0, (s) => s);
    expect(next.scenes).not.toBe(sp.scenes);
  });
});

describe("replaceLine", () => {
  it("returns a new line at sIdx/lIdx and a new lines array", () => {
    const sp = makeSp();
    const next = replaceLine(sp, 0, 1, (l) => ({ ...l, text: "MUTATED" }));
    expect(next.scenes[0].lines![1].text).toBe("MUTATED");
    expect(next.scenes[0].lines).not.toBe(sp.scenes[0].lines);
  });

  it("preserves untouched siblings (= other scenes + other lines + chunks)", () => {
    const sp = makeSp();
    const next = replaceLine(sp, 0, 1, (l) => ({ ...l, text: "MUTATED" }));
    // 別 scene は同参照
    expect(next.scenes[1]).toBe(sp.scenes[1]);
    // 同 scene の別 line は同参照
    expect(next.scenes[0].lines![0]).toBe(sp.scenes[0].lines![0]);
    // 触らなかった line の subtitles 配列も同参照 (= 重要: 巨大 chunk を直列化しない)
    expect(next.scenes[0].lines![0].subtitles).toBe(
      sp.scenes[0].lines![0].subtitles,
    );
  });
});

describe("replaceChunk", () => {
  it("returns a new chunk at sIdx/lIdx/cIdx and new subtitles array", () => {
    const sp = makeSp();
    const next = replaceChunk(sp, 0, 0, 1, (c) => ({ ...c, text: "DONE" }));
    expect(next.scenes[0].lines![0].subtitles![1].text).toBe("DONE");
    expect(next.scenes[0].lines![0].subtitles).not.toBe(
      sp.scenes[0].lines![0].subtitles,
    );
  });

  it("preserves untouched chunks by reference (= path-only copy)", () => {
    const sp = makeSp();
    const next = replaceChunk(sp, 0, 0, 1, (c) => ({ ...c, text: "DONE" }));
    expect(next.scenes[0].lines![0].subtitles![0]).toBe(
      sp.scenes[0].lines![0].subtitles![0],
    );
    // 別 line / 別 scene も同参照
    expect(next.scenes[0].lines![1]).toBe(sp.scenes[0].lines![1]);
    expect(next.scenes[1]).toBe(sp.scenes[1]);
  });

  it("does NOT mutate input screenplay", () => {
    const sp = makeSp();
    const before = JSON.stringify(sp);
    replaceChunk(sp, 0, 0, 1, (c) => ({ ...c, text: "DONE" }));
    expect(JSON.stringify(sp)).toBe(before);
  });
});
