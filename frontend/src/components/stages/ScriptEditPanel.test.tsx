import { describe, expect, it } from "vitest";
import {
  computeDiagnostics,
  hasAnalyzeSpeakerProfiles,
} from "./ScriptEditPanel";
import type { AbstractScene, AbstractScreenplay } from "../../types";

function _abstract(extra: Partial<AbstractScreenplay>): AbstractScreenplay {
  return { caption: "c", scenes: [], ...extra };
}

function _scene(extra: Partial<AbstractScene>): AbstractScene {
  return { lines: [], ...extra } as AbstractScene;
}

describe("hasAnalyzeSpeakerProfiles", () => {
  it("speaker_profiles に 1 件以上あれば true (= analyze が casting 検出した)", () => {
    const abstract = _abstract({
      speaker_profiles: {
        speaker_1: { gender: "female", age_range: "20s" },
      },
    });
    expect(hasAnalyzeSpeakerProfiles(abstract)).toBe(true);
  });

  it("speaker_profiles が未定義なら false", () => {
    expect(hasAnalyzeSpeakerProfiles(_abstract({}))).toBe(false);
  });

  it("speaker_profiles が空 object なら false", () => {
    expect(hasAnalyzeSpeakerProfiles(_abstract({ speaker_profiles: {} }))).toBe(
      false,
    );
  });
});

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
