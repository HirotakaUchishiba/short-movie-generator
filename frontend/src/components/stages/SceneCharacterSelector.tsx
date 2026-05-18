// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
//
// シーンに登場するキャラを画像カードトグルで指定する。
//   - selection が undefined: 既定 (compose の自動推論。視覚的には全 active 表示)
//   - selection が []        : 全 inactive。compose で「人物 0 人」として処理
//   - selection が [...]     : リスト内のキャラだけ active
//
// ボタンクリックで個別 active/inactive を切替。「自動に戻す」ボタンで
// selection を undefined に戻せる。

import { useMemo } from "react";

import { BaseCharacterCard } from "./BaseCharacterCard";
import { groupByBase, joinRef, splitRef } from "./script-edit-utils";

export function SceneCharacterSelector({
  characters,
  selection,
  onChange,
}: {
  characters: string[];
  selection: string[] | undefined;
  /** null = 自動 (= field 削除)、配列 = 明示指定 */
  onChange: (next: string[] | null) => void;
}) {
  const isExplicit = selection !== undefined;
  const cur = isExplicit ? selection! : characters;
  // 表示は featured で選ばれた被写体のみ。各 base で利用可能な衣装は featured
  // 内で同 base の resolved refs から派生 (= シーン別の衣装変更も featured で
  // 宣言済みのバリアントに限定される)。
  const baseGroups = useMemo(() => groupByBase(characters), [characters]);
  const selectedByBase = useMemo(() => {
    const m = new Map<string, string>();
    for (const ref of cur) {
      const { base, wardrobe } = splitRef(ref);
      m.set(base, wardrobe);
    }
    return m;
  }, [cur]);

  const setBase = (baseId: string, wardrobe: string) => {
    const newRef = joinRef(baseId, wardrobe);
    const filtered = cur.filter((r) => splitRef(r).base !== baseId);
    onChange([...filtered, newRef]);
  };
  const clearBase = (baseId: string) => {
    const next = cur.filter((r) => splitRef(r).base !== baseId);
    // 全 base 解除 = 「明示 0 人」ではなく「自動推論に戻す」が自然な操作。
    // 明示的に 0 人 (= 背景のみ) にしたい場合は別途別 path で実現する想定。
    if (next.length === 0) {
      onChange(null);
      return;
    }
    onChange(next);
  };

  return (
    <div className="space-y-2 border-t border-slate-700/50 pt-2">
      <span className="text-xs text-slate-500 shrink-0">登場人物:</span>
      <div className="flex flex-wrap items-start gap-2">
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
              size="sm"
            />
          );
        })}
      </div>
      {isExplicit && (
        <button
          type="button"
          className="text-[11px] text-slate-500 hover:text-slate-300 ml-1"
          onClick={() => onChange(null)}
          title="シーン別指定を解除し compose の既定に戻す"
        >
          ⤺ 自動に戻す
        </button>
      )}
      {isExplicit && selection!.length === 0 && (
        <span className="text-[11px] text-amber-400">
          人物 0 (背景のみ生成)
        </span>
      )}
    </div>
  );
}
