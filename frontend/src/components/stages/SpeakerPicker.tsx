// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
//
// 1 line に対して character/<ref>.png を avatar カードとして並べ、speaker を
// 1 人だけラジオ的に選ばせる。`selected` 未設定時に implicit active
// (= 動画内の他 line で 1 種類しか使われていないキャラを採用) も表示する。

import { useMemo } from "react";

import type { AbstractScreenplay } from "../../types";
import { BaseCharacterCard } from "./BaseCharacterCard";
import {
  collectAllLineSpeakers,
  groupByBase,
  joinRef,
  resolveLineSpeaker,
  splitRef,
} from "./script-edit-utils";

export function SpeakerPicker({
  characters,
  selected,
  allScenes,
  onChange,
  onBulkApply,
}: {
  characters: string[];
  selected: string | undefined;
  /** project の全 scene (= implicit active 判定 + bulk-apply 候補数表示) */
  allScenes: AbstractScreenplay["scenes"];
  onChange: (name: string | undefined) => void;
  /** 同じ「現在 active な speaker」を持つ全 line を newRef に置換する */
  onBulkApply: (oldRef: string, newRef: string) => void;
}) {
  const allSpeakers = useMemo(
    () => collectAllLineSpeakers(allScenes),
    [allScenes],
  );
  const { resolved, implicit } = resolveLineSpeaker(selected, allSpeakers);
  const resolvedBase = resolved ? splitRef(resolved).base : "";
  const resolvedWardrobe = resolved ? splitRef(resolved).wardrobe : "";
  const baseGroups = useMemo(() => groupByBase(characters), [characters]);

  // bulk-apply の候補数: 現在 active な ref を共有する line 数
  // (= 「同 speaker の全 line に適用」ボタンに件数を表示)
  const bulkTargetCount = useMemo(() => {
    if (!resolved) return 0;
    let count = 0;
    for (const sc of allScenes) {
      for (const ln of sc.lines ?? []) {
        if (ln.speaker === resolved) count++;
      }
    }
    return count;
  }, [resolved, allScenes]);

  return (
    <div className="border-t border-slate-700/50 pt-2">
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-[11px] text-slate-400">話者</span>
        <span className="text-[10px] text-slate-500">(1人だけ選択)</span>
        {implicit && resolved && (
          <span
            className="text-[10px] text-slate-400 bg-slate-700/40 rounded px-1.5"
            title={
              `line.speaker 未設定。動画内で他の line が ${resolved} 1 種類` +
              "のみ使っているため自動的にこのキャラを話者として採用しています。" +
              "クリックで明示的に固定できます。"
            }
          >
            自動: {resolved}
          </span>
        )}
        {selected && (
          <button
            type="button"
            className="ml-auto text-[10px] text-slate-500 hover:text-rose-300"
            onClick={() => onChange(undefined)}
            title="話者を未指定に戻す"
          >
            ⤺ クリア
          </button>
        )}
      </div>
      <div role="radiogroup" aria-label="話者" className="flex flex-wrap gap-2">
        {[...baseGroups.entries()].map(([baseId, wardrobes]) => {
          const active = baseId === resolvedBase;
          const wardrobe = active ? resolvedWardrobe : (wardrobes[0] ?? "");
          return (
            <BaseCharacterCard
              key={baseId}
              baseId={baseId}
              wardrobes={wardrobes}
              selectedWardrobe={wardrobe}
              active={active}
              showCheckmark
              onSelect={(w) => {
                const newRef = joinRef(baseId, w);
                if (newRef !== selected) onChange(newRef);
              }}
              size="sm"
            />
          );
        })}
      </div>
      {/* bulk-apply: 同じ speaker を共有する line が 2+ のときだけ表示 */}
      {resolved && bulkTargetCount >= 2 && (
        <div className="mt-2 flex items-center justify-end">
          <button
            type="button"
            className="text-[10px] text-emerald-300 hover:text-emerald-200 hover:bg-emerald-900/30 rounded px-2 py-0.5 border border-emerald-700/40"
            onClick={() => {
              // 現在 active な ref を共有する全 line を resolved に書き換える。
              // 「自動: foo」状態で別キャラに変更したい時の 1 クリック操作。
              const promptText =
                `現在 ${resolved} を話者とする ${bulkTargetCount} line を ` +
                "別キャラに一括変更する場合、変更後のキャラを下のカードで先に選択してください。\n\n" +
                "(= 先にこの行で別カードをクリック → その後で再び本ボタンを押す)";
              if (selected && selected !== resolved) {
                // 既にこの行は別キャラに変更済 → bulk-apply 実行
                onBulkApply(resolved, selected);
              } else {
                window.alert(promptText);
              }
            }}
            title={
              `「${resolved}」を話者とする ${bulkTargetCount} line すべてを、` +
              "この行で選択中のキャラに一括変更します"
            }
          >
            ✓ 同 speaker {bulkTargetCount} line に適用
          </button>
        </div>
      )}
    </div>
  );
}
