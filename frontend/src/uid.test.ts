import { describe, expect, it } from "vitest";
import {
  attachUidsToAbstract,
  attachUidsToScreenplay,
  freshUid,
  stripUids,
} from "./uid";
import type { AbstractScreenplay, Screenplay, SubtitleChunk } from "./types";

describe("freshUid", () => {
  it("呼び出すたびに別の値を返す", () => {
    const a = freshUid();
    const b = freshUid();
    expect(a).not.toBe(b);
  });

  it("非空文字列を返す", () => {
    expect(freshUid().length).toBeGreaterThan(0);
  });
});

describe("attachUidsToScreenplay", () => {
  it("scene / line / subtitle に _uid を付与する", () => {
    const sp: Screenplay = {
      caption: "x",
      scenes: [
        {
          duration: 1,
          lines: [
            {
              text: "hello",
              start: 0,
              subtitles: [{ text: "hello" } as SubtitleChunk],
            },
          ],
        },
      ],
    };
    attachUidsToScreenplay(sp);
    expect(sp.scenes[0]._uid).toBeTruthy();
    expect(sp.scenes[0].lines![0]._uid).toBeTruthy();
    expect(sp.scenes[0].lines![0].subtitles![0]._uid).toBeTruthy();
  });

  it("既存の _uid は保持する (= 再 attach で上書きしない)", () => {
    const sp: Screenplay = {
      scenes: [{ duration: 1, _uid: "preset-scene", lines: [] }],
    };
    attachUidsToScreenplay(sp);
    expect(sp.scenes[0]._uid).toBe("preset-scene");
  });

  it("scenes が空でも例外を投げない", () => {
    const sp: Screenplay = { scenes: [] };
    expect(() => attachUidsToScreenplay(sp)).not.toThrow();
  });

  it("複数 scene の _uid は互いに重複しない", () => {
    const sp: Screenplay = {
      scenes: [
        { duration: 1, lines: [] },
        { duration: 1, lines: [] },
        { duration: 1, lines: [] },
      ],
    };
    attachUidsToScreenplay(sp);
    const uids = sp.scenes.map((s) => s._uid);
    expect(new Set(uids).size).toBe(uids.length);
  });
});

describe("attachUidsToAbstract", () => {
  it("AbstractScene / AbstractLine に _uid を付与する", () => {
    const ab: AbstractScreenplay = {
      caption: "x",
      scenes: [{ lines: [{ text: "a", start: 0 }] }],
    };
    attachUidsToAbstract(ab);
    expect(ab.scenes[0]._uid).toBeTruthy();
    expect(ab.scenes[0].lines[0]._uid).toBeTruthy();
  });
});

describe("stripUids", () => {
  it("_uid を再帰的に削除する", () => {
    const sp: Screenplay = {
      scenes: [
        {
          duration: 1,
          _uid: "s1",
          lines: [
            {
              text: "x",
              start: 0,
              _uid: "l1",
              subtitles: [{ text: "x", _uid: "c1" } as SubtitleChunk],
            },
          ],
        },
      ],
    };
    const cleaned = stripUids(sp);
    expect(cleaned.scenes[0]._uid).toBeUndefined();
    expect(cleaned.scenes[0].lines![0]._uid).toBeUndefined();
    expect(cleaned.scenes[0].lines![0].subtitles![0]._uid).toBeUndefined();
  });

  it("_uid 以外のフィールドは保持する", () => {
    const sp: Screenplay = {
      caption: "keep me",
      scenes: [
        {
          duration: 1.5,
          _uid: "drop",
          background_prompt: "p",
          lines: [{ text: "hi", start: 0, _uid: "drop2", emotion: "驚き" }],
        },
      ],
    };
    const cleaned = stripUids(sp);
    expect(cleaned.caption).toBe("keep me");
    expect(cleaned.scenes[0].duration).toBe(1.5);
    expect(cleaned.scenes[0].background_prompt).toBe("p");
    expect(cleaned.scenes[0].lines![0].emotion).toBe("驚き");
  });

  it("元のオブジェクトを mutate しない", () => {
    const sp: Screenplay = {
      scenes: [{ duration: 1, _uid: "s1", lines: [] }],
    };
    stripUids(sp);
    expect(sp.scenes[0]._uid).toBe("s1");
  });
});
