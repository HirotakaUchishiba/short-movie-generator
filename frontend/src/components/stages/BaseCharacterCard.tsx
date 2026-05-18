// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
//
// 被写体 (base) を 1 枚カード化し、内部 select で衣装を切替する共通カード。
//
// - 画像クリック → active なら `onClear`、非 active なら
//   `onSelect(selectedWardrobe)` で active 化
// - 衣装 select 変更 → `onSelect(newWardrobe)` (= active 化しつつ衣装更新)
//
// `selectedWardrobe` は active 時 = 現在の衣装、非 active 時 = カードのプレビュー
// 用衣装 (= 利用可能な衣装の先頭)。利用可能衣装が 1 つだけならドロップダウンを
// 出さず static 表示。

import { characterAssetUrl } from "../../api";
import { joinRef, wardrobeLabel } from "./script-edit-utils";

export function BaseCharacterCard({
  baseId,
  wardrobes,
  selectedWardrobe,
  active,
  showCheckmark = false,
  onSelect,
  onClear,
  size = "md",
}: {
  baseId: string;
  wardrobes: string[];
  selectedWardrobe: string;
  active: boolean;
  showCheckmark?: boolean;
  onSelect: (wardrobe: string) => void;
  onClear?: () => void;
  size?: "md" | "sm";
}) {
  const previewRef = joinRef(baseId, selectedWardrobe);
  const widthCls = size === "sm" ? "w-16" : "w-full";
  const handleCardClick = () => {
    if (active && onClear) onClear();
    else onSelect(selectedWardrobe);
  };
  return (
    <div
      className={`relative flex flex-col items-stretch rounded-lg border-2 overflow-hidden transition ${widthCls} ${
        active
          ? "border-emerald-500 bg-emerald-900/30"
          : "border-slate-700 bg-slate-900/40 opacity-60 hover:opacity-100"
      }`}
    >
      <button
        type="button"
        onClick={handleCardClick}
        className="relative block w-full text-left"
        title={
          active
            ? `${baseId} を解除`
            : `${joinRef(baseId, selectedWardrobe)} を選択`
        }
      >
        {showCheckmark && active && (
          <span
            className="absolute top-1 right-1 w-4 h-4 bg-emerald-500 text-slate-900 text-[10px] font-bold rounded-full flex items-center justify-center z-10"
            aria-hidden
          >
            ✓
          </span>
        )}
        <img
          src={characterAssetUrl(previewRef)}
          alt={previewRef}
          className={`w-full aspect-[9/16] object-cover bg-slate-900 ${
            active ? "" : "grayscale"
          }`}
          onError={(e) => {
            (e.target as HTMLImageElement).style.opacity = "0.2";
          }}
        />
        <div
          className={`text-[11px] py-0.5 px-1 truncate w-full text-center ${
            active ? "text-emerald-200 font-semibold" : "text-slate-400"
          }`}
        >
          {baseId}
        </div>
      </button>
      <div className="px-1 pb-1">
        {wardrobes.length > 1 ? (
          <select
            className="text-[10px] w-full py-0.5 px-1 bg-slate-900/60 border border-slate-700 rounded text-slate-300"
            value={selectedWardrobe}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => onSelect(e.target.value)}
            title="衣装を変更"
          >
            {wardrobes.map((w) => (
              <option key={w || "_base"} value={w}>
                {wardrobeLabel(w)}
              </option>
            ))}
          </select>
        ) : (
          <div className="text-[10px] text-slate-500 truncate w-full text-center py-0.5">
            {wardrobeLabel(selectedWardrobe)}
          </div>
        )}
      </div>
    </div>
  );
}
