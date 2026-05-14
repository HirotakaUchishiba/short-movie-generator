import { describe, expect, it } from "vitest";
import { hasAnalyzeSpeakerProfiles } from "./ScriptEditPanel";
import type { AbstractScreenplay } from "../../types";

function _abstract(extra: Partial<AbstractScreenplay>): AbstractScreenplay {
  return { caption: "c", scenes: [], ...extra };
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
