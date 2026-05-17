import { describe, expect, it } from "vitest";
import {
  collectRawSpeakers,
  computeDiagnostics,
  hasAnalyzeSpeakerProfiles,
  resolveLineSpeaker,
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

describe("collectRawSpeakers: 3 つの source の和集合で抽出", () => {
  it("speaker_profiles だけが populate されている場合も拾う (= bug fix)", () => {
    // analyze が speaker_profiles を出したが line.speaker / speaker_to_ref は
    // 空のケース。旧実装ではここで rawSpeakers が空になり SpeakerMappingSection
    // が render されなかった。
    const abstract = _abstract({
      speaker_profiles: {
        speaker_1: { gender: "male", age_range: "30s" },
      },
      scenes: [_scene({ lines: [{ text: "a", emotion: "中立" }] as never })],
    });
    const result = collectRawSpeakers(abstract);
    expect(result).toEqual([{ id: "speaker_1", lines: 0, scenes: 0 }]);
  });

  it("speaker_to_ref だけが populate されている場合も拾う", () => {
    const abstract = _abstract({
      speaker_to_ref: { speaker_1: "f1__office" },
      scenes: [_scene({ lines: [{ text: "a", emotion: "中立" }] as never })],
    });
    const result = collectRawSpeakers(abstract);
    expect(result).toEqual([{ id: "speaker_1", lines: 0, scenes: 0 }]);
  });

  it("line.speaker だけが populate されている場合も拾う (= 旧挙動互換)", () => {
    const abstract = _abstract({
      scenes: [
        _scene({
          lines: [
            { text: "a", emotion: "中立", speaker: "speaker_1" },
            { text: "b", emotion: "中立", speaker: "speaker_1" },
          ] as never,
        }),
        _scene({
          lines: [
            { text: "c", emotion: "中立", speaker: "speaker_2" },
          ] as never,
        }),
      ],
    });
    const result = collectRawSpeakers(abstract);
    expect(result).toEqual([
      { id: "speaker_1", lines: 2, scenes: 1 },
      { id: "speaker_2", lines: 1, scenes: 1 },
    ]);
  });

  it("3 source の和集合 (= sorted、行数は line.speaker のみから集計)", () => {
    const abstract = _abstract({
      speaker_profiles: { speaker_3: { gender: "male" } },
      speaker_to_ref: { speaker_2: "m1__casual" },
      scenes: [
        _scene({
          lines: [
            { text: "a", emotion: "中立", speaker: "speaker_1" },
          ] as never,
        }),
      ],
    });
    const result = collectRawSpeakers(abstract);
    expect(result).toEqual([
      { id: "speaker_1", lines: 1, scenes: 1 },
      { id: "speaker_2", lines: 0, scenes: 0 }, // speaker_to_ref から
      { id: "speaker_3", lines: 0, scenes: 0 }, // speaker_profiles から
    ]);
  });

  it("3 source 全て空 → 空配列 (= 単一人物動画想定)", () => {
    const abstract = _abstract({
      scenes: [_scene({ lines: [{ text: "a", emotion: "中立" }] as never })],
    });
    expect(collectRawSpeakers(abstract)).toEqual([]);
  });

  it("非 speaker_N 形式 (= 既に resolved されたキー) は除外する", () => {
    const abstract = _abstract({
      speaker_profiles: {
        speaker_1: { gender: "male" },
        m1__casual: { gender: "male" }, // 不正な形式
      },
      speaker_to_ref: {
        f1__office: "f1__office", // 不正な形式
      },
      scenes: [
        _scene({
          lines: [
            { text: "a", emotion: "中立", speaker: "speaker_1" },
            { text: "b", emotion: "中立", speaker: "f1__office" }, // resolved
          ] as never,
        }),
      ],
    });
    const result = collectRawSpeakers(abstract);
    expect(result).toEqual([{ id: "speaker_1", lines: 1, scenes: 1 }]);
  });

  it("重複 speaker_N (= 複数 source に同時に出現) は 1 つに統合", () => {
    const abstract = _abstract({
      speaker_profiles: { speaker_1: { gender: "male" } },
      speaker_to_ref: { speaker_1: "f1__office" },
      scenes: [
        _scene({
          lines: [
            { text: "a", emotion: "中立", speaker: "speaker_1" },
          ] as never,
        }),
      ],
    });
    const result = collectRawSpeakers(abstract);
    expect(result).toEqual([{ id: "speaker_1", lines: 1, scenes: 1 }]);
  });
});

describe("resolveLineSpeaker: per-line picker の active 解決", () => {
  it("selected が raw speaker_N → speakerToRef で resolve", () => {
    const result = resolveLineSpeaker("speaker_1", {
      speaker_1: "f1__office",
    });
    expect(result).toEqual({ resolved: "f1__office", implicit: false });
  });

  it("selected が既に resolved id → そのまま返す", () => {
    const result = resolveLineSpeaker("m2__casual", {
      speaker_1: "m2__casual",
    });
    expect(result).toEqual({ resolved: "m2__casual", implicit: false });
  });

  it("selected 未設定 + speakerToRef が 1 entry → implicit active (= bug fix の中核)", () => {
    // 旧 analyze で line.speaker が null のまま snapshot された project が
    // この経路に来る。speakerToRef の唯一の値を implicit active として表示。
    const result = resolveLineSpeaker(undefined, {
      speaker_1: "m2__casual",
    });
    expect(result).toEqual({ resolved: "m2__casual", implicit: true });
  });

  it("selected 未設定 + speakerToRef が 0 entry → undefined (= active なし)", () => {
    const result = resolveLineSpeaker(undefined, {});
    expect(result).toEqual({ resolved: undefined, implicit: false });
  });

  it("selected 未設定 + speakerToRef が 2+ entry → undefined (= ambiguous)", () => {
    // 複数 speaker のうち誰なのか不明 → ユーザに選ばせる
    const result = resolveLineSpeaker(undefined, {
      speaker_1: "f1__office",
      speaker_2: "m1__suit",
    });
    expect(result).toEqual({ resolved: undefined, implicit: false });
  });

  it("raw speaker_N が speakerToRef に無い → resolved undefined + implicit=false", () => {
    // 未マッピング speaker (= UI で「未マッピング」バッジが出るケース)
    const result = resolveLineSpeaker("speaker_3", {
      speaker_1: "f1__office",
    });
    expect(result).toEqual({ resolved: undefined, implicit: false });
  });
});
