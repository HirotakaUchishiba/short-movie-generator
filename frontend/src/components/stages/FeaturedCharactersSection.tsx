// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
//
// 動画全体の登場人物を characters/ 配下の画像から選択するセクション。
// 選択された ref は abstract.featured_characters に保存され、各シーンの
// SceneCharacterSelector / SpeakerPicker の候補として使われる。

import { useMemo } from "react";

import { AnalyzeSuggestedBadge } from "./AnalyzeSuggestedBadge";
import { BaseCharacterCard } from "./BaseCharacterCard";
import { groupByBase, joinRef, splitRef } from "./script-edit-utils";

export function FeaturedCharactersSection({
  allRefs,
  selected,
  isExplicit,
  analyzeSuggested,
  onChange,
  onClearExplicit,
}: {
  allRefs: string[];
  /** 表示上アクティブな ref 一覧 (= explicit なら featured_characters、未指定なら fallback list) */
  selected: string[];
  /** abstract.featured_characters が明示的に書かれているか */
  isExplicit: boolean;
  /** analyze が casting 検出を実行したか (= 「✨ analyze 推定」バッジ表示) */
  analyzeSuggested: boolean;
  onChange: (next: string[]) => void;
  onClearExplicit: () => void;
}) {
  const baseGroups = useMemo(() => groupByBase(allRefs), [allRefs]);
  // selected の中で base 単位の選択状態 (= base → 衣装) を抽出。同 base の
  // 重複は禁止 (= 衣装変更で旧 ref は入れ替え)
  const selectedByBase = useMemo(() => {
    const m = new Map<string, string>();
    for (const ref of selected) {
      const { base, wardrobe } = splitRef(ref);
      m.set(base, wardrobe);
    }
    return m;
  }, [selected]);

  if (allRefs.length === 0) {
    return (
      <div className="border border-slate-700 rounded p-2 text-xs text-slate-500">
        characters/ ディレクトリに画像がありません。
      </div>
    );
  }

  const setBase = (baseId: string, wardrobe: string) => {
    const newRef = joinRef(baseId, wardrobe);
    const filtered = selected.filter((r) => splitRef(r).base !== baseId);
    onChange([...filtered, newRef]);
  };
  const clearBase = (baseId: string) => {
    onChange(selected.filter((r) => splitRef(r).base !== baseId));
  };

  return (
    <div className="border border-slate-700 rounded p-2 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-slate-300 font-medium">👥 登場人物</span>
        <span className="text-[11px] text-slate-500">
          被写体ごとに 1 衣装を選択 ({selected.length} 人)
          {!isExplicit && <span className="ml-2 text-amber-400">(未指定)</span>}
        </span>
        {analyzeSuggested && isExplicit && <AnalyzeSuggestedBadge />}
        {isExplicit && (
          <button
            type="button"
            className="ml-auto text-[11px] text-slate-500 hover:text-slate-300"
            onClick={onClearExplicit}
            title="明示指定を解除"
          >
            ⤺ 自動に戻す
          </button>
        )}
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
        {[...baseGroups.entries()].map(([baseId, wardrobes]) => {
          const active = selectedByBase.has(baseId);
          const wardrobe = selectedByBase.get(baseId) ?? wardrobes[0] ?? "";
          return (
            <BaseCharacterCard
              key={baseId}
              baseId={baseId}
              wardrobes={wardrobes}
              selectedWardrobe={wardrobe}
              active={active}
              onSelect={(w) => setBase(baseId, w)}
              onClear={() => clearBase(baseId)}
            />
          );
        })}
      </div>
    </div>
  );
}
