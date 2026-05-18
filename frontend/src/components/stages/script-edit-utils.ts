// Stage 1 (ScriptEditPanel) で使う resolved id / speaker 系の pure helper 群。
//
// ScriptEditPanel.tsx から段階分離 (= 計画書 §3.1.3-b)。今後 SpeakerPicker /
// BaseCharacterCard / FeaturedCharactersSection を独立ファイルに抽出する際、
// 共通 helper として両方から import できるようにする。
//
// すべて pure function で副作用なし。React に依存しない (= 単体テスト容易)。

import type { AbstractDiagnostics, AbstractScreenplay } from "../../types";

/** カメラ距離の選択肢 (= scenes[].camera_distance の enum)。
 *  ScriptEditPanel の UI dropdown / computeDiagnostics の validation で使用。 */
export const CAMERA_DISTANCE_OPTIONS = [
  { value: "close-up", label: "close-up (顔寄り)" },
  { value: "medium-close", label: "medium-close (胸〜顔)" },
  { value: "medium", label: "medium (腰〜顔)" },
  { value: "wide", label: "wide (全身)" },
] as const;

/** resolved id (= `"<base>__<wardrobe>"` or `"<base>"`) を分解する。 */
export function splitRef(ref: string): { base: string; wardrobe: string } {
  const i = ref.indexOf("__");
  return i < 0
    ? { base: ref, wardrobe: "" }
    : { base: ref.slice(0, i), wardrobe: ref.slice(i + 2) };
}

/** base + wardrobe を resolved id に再合成する (`wardrobe === ""` なら base 単独)。 */
export function joinRef(base: string, wardrobe: string): string {
  return wardrobe ? `${base}__${wardrobe}` : base;
}

/** resolved refs を base 単位にグルーピングし、各 base の利用可能 wardrobes
 *  list を返す (`""` = base.png 単独)。base の登場順を保ち、wardrobe は昇順。 */
export function groupByBase(refs: string[]): Map<string, string[]> {
  const out = new Map<string, Set<string>>();
  for (const ref of refs) {
    const { base, wardrobe } = splitRef(ref);
    if (!out.has(base)) out.set(base, new Set());
    out.get(base)!.add(wardrobe);
  }
  const result = new Map<string, string[]>();
  for (const [base, set] of out) {
    result.set(base, [...set].sort());
  }
  return result;
}

export const wardrobeLabel = (w: string): string => w || "base";

/**
 * line.speaker が明示されていない場合に、scene の他 line の speaker から
 * 単一候補が決まるならそれを implicit active として返す。
 */
export function resolveLineSpeaker(
  selected: string | undefined,
  siblingSpeakers: string[] = [],
): { resolved: string | undefined; implicit: boolean } {
  if (selected) {
    return { resolved: selected, implicit: false };
  }
  const uniq = Array.from(new Set(siblingSpeakers.filter(Boolean)));
  if (uniq.length === 1) {
    return { resolved: uniq[0], implicit: true };
  }
  return { resolved: undefined, implicit: false };
}

/** 全 scene を走査して line.speaker のユニーク集合を返す (= bulk-apply / implicit
 *  active 判定に使う)。 */
export function collectAllLineSpeakers(
  scenes: AbstractScreenplay["scenes"],
): string[] {
  const set = new Set<string>();
  for (const sc of scenes) {
    for (const ln of sc.lines ?? []) {
      if (typeof ln.speaker === "string" && ln.speaker) {
        set.add(ln.speaker);
      }
    }
  }
  return [...set].sort();
}

/**
 * 旧 raw `speaker_N` 形式の残骸を検出する (= 2026-05-17 schema 撤廃後の互換性確認用)。
 *
 * 撤廃後は line.speaker に resolved id を直書きする方式に変わったため、
 * 旧 raw `speaker_N` 形式は migration script で resolved id に変換される
 * 前提。残っていれば migration 漏れの警告として diagnostic に表示する。
 */
export function collectRawSpeakerResidue(
  abstract: AbstractScreenplay,
): string[] {
  const allIds = new Set<string>();
  const isRawSpeakerId = (s: string) => /^speaker_\d+$/i.test(s);
  for (let sIdx = 0; sIdx < abstract.scenes.length; sIdx++) {
    for (const line of abstract.scenes[sIdx].lines ?? []) {
      const sp = line.speaker;
      if (sp && isRawSpeakerId(sp)) allIds.add(sp);
    }
  }
  return [...allIds].sort();
}

/**
 * frontend 側で abstract から `AbstractDiagnostics` を再計算する。
 * `analyze.compose.diagnose_abstract` (Python) と挙動を合わせる必要がある。
 *
 * `availableCharacters` は `api.listCharacters()` から取れる resolved id の配列。
 * 空配列なら character ref 物理存在検証はスキップ (= テスト・初期化中の挙動と
 * server 側 conftest のスタブと同等)。
 */
export function computeDiagnostics(
  abstract: AbstractScreenplay,
  availableCharacters: string[],
): AbstractDiagnostics {
  const featured = (abstract.featured_characters ?? []).filter(
    (c): c is string => typeof c === "string" && !!c,
  );
  const availableSet = new Set(availableCharacters);
  const skipCharCheck = availableSet.size === 0;
  const isUnknownRef = (ref: unknown): ref is string =>
    !skipCharCheck &&
    typeof ref === "string" &&
    ref !== "" &&
    !availableSet.has(ref);

  const rawSpeakerResidue = new Set<string>();
  const scenesWithoutCharacters: number[] = [];
  const scenesWithoutLocation: number[] = [];
  const invalidCamera: { scene_idx: number; value: string }[] = [];
  const validCameras = new Set(
    CAMERA_DISTANCE_OPTIONS.map((c) => c.value as string),
  );
  const unknown = {
    featured: [] as string[],
    character_selection: [] as { scene_idx: number; ref: string }[],
    speaker: [] as { scene_idx: number; line_idx: number; ref: string }[],
  };

  for (const ref of featured) {
    if (isUnknownRef(ref)) unknown.featured.push(ref);
  }

  abstract.scenes.forEach((scene, sIdx) => {
    const loc = scene.location_ref;
    if (typeof loc !== "string" || !loc) {
      scenesWithoutLocation.push(sIdx);
    }
    const cam = scene.camera_distance;
    if (typeof cam === "string" && cam && !validCameras.has(cam)) {
      invalidCamera.push({ scene_idx: sIdx, value: cam });
    }
    const sel = scene.character_selection;
    if (Array.isArray(sel)) {
      for (const ref of sel) {
        if (isUnknownRef(ref)) {
          unknown.character_selection.push({ scene_idx: sIdx, ref });
        }
      }
    }

    (scene.lines ?? []).forEach((line, lIdx) => {
      const sp = line.speaker;
      if (!sp || typeof sp !== "string") return;
      if (/^speaker_\d+$/i.test(sp)) {
        rawSpeakerResidue.add(sp);
        return;
      }
      if (isUnknownRef(sp)) {
        unknown.speaker.push({ scene_idx: sIdx, line_idx: lIdx, ref: sp });
      }
    });

    // シーン人物推論を再現して 0 人になるかチェック。
    // featured が空のとき (= 動画全体が「人物無し」の意図) は警告抑制し、
    // false-positive を避ける (= 別途 featuredEmpty 警告で気付ける)。
    if ("character_selection" in scene) {
      if (Array.isArray(sel) && sel.length === 0 && featured.length > 0) {
        scenesWithoutCharacters.push(sIdx);
      }
      return;
    }
    if (featured.length === 0) return;
    const speakers = new Set<string>();
    for (const line of scene.lines ?? []) {
      if (line.speaker) speakers.add(line.speaker);
    }
    const resolved = new Set<string>();
    for (const sp of speakers) {
      if (featured.includes(sp)) resolved.add(sp);
    }
    if (resolved.size === 0) {
      scenesWithoutCharacters.push(sIdx);
    }
  });

  return {
    unmapped_speakers: [...rawSpeakerResidue].sort(),
    scenes_without_characters: scenesWithoutCharacters,
    scenes_without_location: scenesWithoutLocation,
    invalid_camera_distance: invalidCamera,
    unknown_character_refs: unknown,
  };
}
