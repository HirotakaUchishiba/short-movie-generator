// Stage 1 (ScriptEditPanel) で使う resolved id / speaker 系の pure helper 群。
//
// ScriptEditPanel.tsx から段階分離 (= 計画書 §3.1.3-b)。今後 SpeakerPicker /
// BaseCharacterCard / FeaturedCharactersSection を独立ファイルに抽出する際、
// 共通 helper として両方から import できるようにする。
//
// すべて pure function で副作用なし。React に依存しない (= 単体テスト容易)。

import type { AbstractScreenplay } from "../../types";

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
