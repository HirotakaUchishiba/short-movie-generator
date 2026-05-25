import { describe, expect, it } from "vitest";

import { applyFeaturedSpeakerFollow } from "./script-edit-utils";
import type { AbstractScene, AbstractScreenplay } from "../../types";

function _scene(speakers: (string | undefined)[]): AbstractScene {
  return {
    lines: speakers.map((sp, i) => ({
      text: `l${i}`,
      start: 0,
      emotion: "中立",
      ...(sp !== undefined ? { speaker: sp } : {}),
    })),
  } as AbstractScene;
}

function _abstract(
  featured: string[] | undefined,
  scenes: AbstractScene[],
): AbstractScreenplay {
  return {
    caption: "c",
    scenes,
    ...(featured !== undefined ? { featured_characters: featured } : {}),
  };
}

function speakersOf(
  scenes: AbstractScreenplay["scenes"],
): (string | undefined)[][] {
  return scenes.map((sc) => (sc.lines ?? []).map((ln) => ln.speaker));
}

describe("applyFeaturedSpeakerFollow", () => {
  it("(a) 1:1 置換 f1 → m3 で全 line.speaker=f1 が m3 に変わる", () => {
    const abstract = _abstract(
      ["f1", "m1"],
      [_scene(["f1", "m1"]), _scene(["f1", "f1", "m1"])],
    );
    const scenes = applyFeaturedSpeakerFollow(abstract, ["m3", "m1"]);
    expect(speakersOf(scenes)).toEqual([
      ["m3", "m1"],
      ["m3", "m3", "m1"],
    ]);
    // イミュータブル: 元の abstract は不変
    expect(speakersOf(abstract.scenes)).toEqual([
      ["f1", "m1"],
      ["f1", "f1", "m1"],
    ]);
  });

  it("(a') 1:1 置換は wardrobe 込みの新 resolved id へ追従する", () => {
    const abstract = _abstract(["f1__office"], [_scene(["f1__office", "f1"])]);
    // f1 base を m3__suit に置換 (= base f1 削除 + base m3 追加)
    const scenes = applyFeaturedSpeakerFollow(abstract, ["m3__suit"]);
    // speaker の base が f1 の line はすべて wardrobe 込み m3__suit へ
    expect(speakersOf(scenes)).toEqual([["m3__suit", "m3__suit"]]);
  });

  it("(b) 複数置換は不変 (f1,m1 → m3,m4)", () => {
    const abstract = _abstract(["f1", "m1"], [_scene(["f1", "m1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["m3", "m4"]);
    expect(speakersOf(scenes)).toEqual([["f1", "m1"]]);
  });

  it("(c) 追加のみは不変 (f1 → f1,m3)", () => {
    const abstract = _abstract(["f1"], [_scene(["f1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["f1", "m3"]);
    expect(speakersOf(scenes)).toEqual([["f1"]]);
  });

  it("(d) 削除のみは不変 (f1,m1 → f1)", () => {
    const abstract = _abstract(["f1", "m1"], [_scene(["f1", "m1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["f1"]);
    expect(speakersOf(scenes)).toEqual([["f1", "m1"]]);
  });

  it("変化なしは不変 (= 同 base 集合)", () => {
    const abstract = _abstract(["f1", "m1"], [_scene(["f1", "m1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["f1", "m1"]);
    expect(speakersOf(scenes)).toEqual([["f1", "m1"]]);
  });

  it("featured_characters が未定義 (= 配列でない) でも安全に no-op", () => {
    const abstract = _abstract(undefined, [_scene(["f1"])]);
    // 旧 base 集合は空 → added のみ → 不変
    const scenes = applyFeaturedSpeakerFollow(abstract, ["m3"]);
    expect(speakersOf(scenes)).toEqual([["f1"]]);
  });
});
