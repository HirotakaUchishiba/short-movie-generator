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
  // ── ケース1: featured が 1 人だけ → featured に無い speaker を寄せる ──

  it("複数話者 → featured 1 人で、消えた speaker も含め全て 1 人へ (f1__office,m3 → m3)", () => {
    // 今回の実バグ: featured を [m3] に絞ったのに f1__office が残り f1 の声が出た
    const abstract = _abstract(
      ["f1__office", "m3"],
      [_scene(["f1__office", "m3"]), _scene(["f1__office"])],
    );
    const scenes = applyFeaturedSpeakerFollow(abstract, ["m3"]);
    expect(speakersOf(scenes)).toEqual([["m3", "m3"], ["m3"]]);
  });

  it("featured が 1 人に減ったら残った 1 人へ寄せる (f1,m1 → f1)", () => {
    const abstract = _abstract(["f1", "m1"], [_scene(["f1", "m1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["f1"]);
    expect(speakersOf(scenes)).toEqual([["f1", "f1"]]);
  });

  it("1 人への置換は wardrobe 込みの新 resolved id へ追従 (f1__office → m3__suit)", () => {
    const abstract = _abstract(["f1__office"], [_scene(["f1__office", "f1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["m3__suit"]);
    expect(speakersOf(scenes)).toEqual([["m3__suit", "m3__suit"]]);
    // イミュータブル: 元の abstract は不変
    expect(speakersOf(abstract.scenes)).toEqual([["f1__office", "f1"]]);
  });

  it("featured 未定義から 1 人に設定 → 全 line をその 1 人へ (→ m3)", () => {
    const abstract = _abstract(undefined, [_scene(["f1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["m3"]);
    expect(speakersOf(scenes)).toEqual([["m3"]]);
  });

  // ── ケース2: featured 2 人以上のまま base 1:1 置換 ──

  it("featured 2 人で 1:1 置換 (f1,m1 → m3,m1): f1 系のみ m3 へ", () => {
    const abstract = _abstract(
      ["f1", "m1"],
      [_scene(["f1", "m1"]), _scene(["f1", "f1", "m1"])],
    );
    const scenes = applyFeaturedSpeakerFollow(abstract, ["m3", "m1"]);
    expect(speakersOf(scenes)).toEqual([
      ["m3", "m1"],
      ["m3", "m3", "m1"],
    ]);
  });

  // ── 連動しない (安全側) ケース ──

  it("複数置換は不変 (f1,m1 → m3,m4)", () => {
    const abstract = _abstract(["f1", "m1"], [_scene(["f1", "m1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["m3", "m4"]);
    expect(speakersOf(scenes)).toEqual([["f1", "m1"]]);
  });

  it("追加のみ (2 人以上に) は不変 (f1 → f1,m3)", () => {
    const abstract = _abstract(["f1"], [_scene(["f1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["f1", "m3"]);
    expect(speakersOf(scenes)).toEqual([["f1"]]);
  });

  it("複数削除で 2 人以上残るは不変 (f1,m1,m2 → f1,m1)", () => {
    const abstract = _abstract(
      ["f1", "m1", "m2"],
      [_scene(["f1", "m1", "m2"])],
    );
    const scenes = applyFeaturedSpeakerFollow(abstract, ["f1", "m1"]);
    expect(speakersOf(scenes)).toEqual([["f1", "m1", "m2"]]);
  });

  it("変化なしは不変 (同 base 集合)", () => {
    const abstract = _abstract(["f1", "m1"], [_scene(["f1", "m1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["f1", "m1"]);
    expect(speakersOf(scenes)).toEqual([["f1", "m1"]]);
  });

  it("featured 未定義から 2 人以上に設定は不変 (→ m3,m4)", () => {
    const abstract = _abstract(undefined, [_scene(["f1"])]);
    const scenes = applyFeaturedSpeakerFollow(abstract, ["m3", "m4"]);
    expect(speakersOf(scenes)).toEqual([["f1"]]);
  });
});
