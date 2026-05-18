// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
//
// 全シーンに同じ値を一括適用するセレクタ。17 シーンクリック地獄を回避するため、
// animation_style を bulk apply できる (= location_ref / camera_distance は
// analyze が SSOT)。

import { useState } from "react";

const BULK_ANIM = ["subtle", "standard", "expressive"] as const;

export function BulkApplyBar({
  onApply,
}: {
  onApply: (field: "animation_style", value: string | undefined) => void;
}) {
  const [animVal, setAnimVal] = useState("");
  return (
    <div className="border border-slate-700 rounded p-2 space-y-2 bg-slate-800/30">
      <span className="text-[11px] text-slate-400 block">
        🪄 全シーンに一括適用 (個別シーンの値を上書きします)
      </span>
      <div className="flex flex-wrap gap-3 text-xs items-center">
        <label className="flex items-center gap-1">
          <span className="text-slate-500 shrink-0">動き</span>
          <select
            className="select text-xs"
            value={animVal}
            onChange={(e) => {
              const v = e.target.value;
              if (v) onApply("animation_style", v);
              setAnimVal("");
            }}
          >
            <option value="">(選んで適用)</option>
            {BULK_ANIM.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
