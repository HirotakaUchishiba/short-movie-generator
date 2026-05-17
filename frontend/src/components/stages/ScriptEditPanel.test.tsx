import { describe, expect, it } from "vitest";
import {
  collectRawSpeakerResidue,
  computeDiagnostics,
  resolveLineSpeaker,
} from "./ScriptEditPanel";
import type { AbstractScene, AbstractScreenplay } from "../../types";

function _abstract(extra: Partial<AbstractScreenplay>): AbstractScreenplay {
  return { caption: "c", scenes: [], ...extra };
}

function _scene(extra: Partial<AbstractScene>): AbstractScene {
  return { lines: [], ...extra } as AbstractScene;
}

// ─── computeDiagnostics: location / camera_distance ────────────────────

describe("computeDiagnostics: location / camera_distance", () => {
  it("location_ref が空のシーンを scenes_without_location に集める", () => {
    const abstract = _abstract({
      scenes: [
        _scene({ location_ref: "home_office" }),
        _scene({}), // location_ref 無し
        _scene({ location_ref: "" }), // 空文字
      ],
    });
    const diag = computeDiagnostics(abstract, []);
    expect(diag.scenes_without_location).toEqual([1, 2]);
  });

  it("全シーンに location_ref があれば scenes_without_location は空", () => {
    const abstract = _abstract({
      scenes: [
        _scene({ location_ref: "home_office" }),
        _scene({ location_ref: "warm_cafe" }),
      ],
    });
    const diag = computeDiagnostics(abstract, []);
    expect(diag.scenes_without_location).toEqual([]);
  });

  it("enum 外の camera_distance を invalid_camera_distance に集める", () => {
    const abstract = _abstract({
      scenes: [
        _scene({ camera_distance: "medium" }), // valid
        _scene({ camera_distance: "extra-zoom" as never }), // invalid
        _scene({}), // 未設定 → invalid 判定対象外
      ],
    });
    const diag = computeDiagnostics(abstract, []);
    expect(diag.invalid_camera_distance).toEqual([
      { scene_idx: 1, value: "extra-zoom" },
    ]);
  });

  it("camera_distance 未設定 (= analyze の自動 fallback に委ねる) は invalid 扱いしない", () => {
    const abstract = _abstract({
      scenes: [_scene({}), _scene({ camera_distance: "" as never })],
    });
    const diag = computeDiagnostics(abstract, []);
    expect(diag.invalid_camera_distance).toEqual([]);
  });
});

// ─── collectRawSpeakerResidue (= 旧 speaker_N migration 漏れ検出) ────

describe("collectRawSpeakerResidue: 旧 raw 形式の残骸検出", () => {
  it("line.speaker に旧 raw speaker_N が残っていれば検出", () => {
    const abstract = _abstract({
      scenes: [
        _scene({
          lines: [
            { text: "a", emotion: "中立", speaker: "speaker_1" },
            { text: "b", emotion: "中立", speaker: "speaker_2" },
          ] as never,
        }),
      ],
    });
    expect(collectRawSpeakerResidue(abstract)).toEqual([
      "speaker_1",
      "speaker_2",
    ]);
  });

  it("resolved id のみなら空配列 (= migration 済み)", () => {
    const abstract = _abstract({
      scenes: [
        _scene({
          lines: [
            { text: "a", emotion: "中立", speaker: "f1__office" },
            { text: "b", emotion: "中立", speaker: "m1__suit" },
          ] as never,
        }),
      ],
    });
    expect(collectRawSpeakerResidue(abstract)).toEqual([]);
  });

  it("混在ケースでも raw のみ抽出", () => {
    const abstract = _abstract({
      scenes: [
        _scene({
          lines: [
            { text: "a", emotion: "中立", speaker: "f1__office" },
            { text: "b", emotion: "中立", speaker: "speaker_3" },
          ] as never,
        }),
      ],
    });
    expect(collectRawSpeakerResidue(abstract)).toEqual(["speaker_3"]);
  });
});

// ─── resolveLineSpeaker (= per-line picker active 解決) ────────────────

describe("resolveLineSpeaker: per-line picker の active 解決", () => {
  it("selected が resolved id → そのまま返す", () => {
    const result = resolveLineSpeaker("m2__casual", ["m2__casual"]);
    expect(result).toEqual({ resolved: "m2__casual", implicit: false });
  });

  it("selected 未設定 + siblingSpeakers が 1 種類 → implicit active", () => {
    // 他の line がすべて m2__casual → 暗黙でこの line も m2__casual と推定
    const result = resolveLineSpeaker(undefined, [
      "m2__casual",
      "m2__casual",
      "m2__casual",
    ]);
    expect(result).toEqual({ resolved: "m2__casual", implicit: true });
  });

  it("selected 未設定 + siblingSpeakers が空 → undefined", () => {
    const result = resolveLineSpeaker(undefined, []);
    expect(result).toEqual({ resolved: undefined, implicit: false });
  });

  it("selected 未設定 + siblingSpeakers が 2+ 種類 → undefined (= ambiguous)", () => {
    const result = resolveLineSpeaker(undefined, ["f1__office", "m1__suit"]);
    expect(result).toEqual({ resolved: undefined, implicit: false });
  });

  it("空文字や falsy は無視される", () => {
    const result = resolveLineSpeaker(undefined, [
      "f1__office",
      "",
      "f1__office",
    ]);
    // 空文字 filter 後 1 種類 → implicit active
    expect(result).toEqual({ resolved: "f1__office", implicit: true });
  });
});
