// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
//
// シーンの背景 (= location_ref) を選ぶ。analyze が pre-fill した値を初期表示し、
// ユーザが訂正できる。空選択で `(未設定)` (= completeness banner で警告)。
//
// 2026-05-25: 中身を <select> から LocationThumbPicker (= preview.png のサムネ
// グリッド) に差し替え (callsite は不変)。

import type { AbstractScreenplay } from "../../types";
import { LocationThumbPicker } from "./LocationThumbPicker";

export function LocationPicker({
  scene,
  locationIds,
  onSceneChange,
}: {
  scene: AbstractScreenplay["scenes"][number];
  locationIds: string[];
  onSceneChange: (
    fn: (
      s: AbstractScreenplay["scenes"][number],
    ) => AbstractScreenplay["scenes"][number],
  ) => void;
}) {
  return (
    <div className="space-y-1">
      <span className="text-xs text-slate-500">🏠 背景</span>
      <LocationThumbPicker
        locationIds={locationIds}
        value={scene.location_ref}
        onChange={(v) =>
          onSceneChange((s) => {
            const next = { ...s };
            if (v) {
              next.location_ref = v;
            } else {
              delete (next as Record<string, unknown>).location_ref;
            }
            return next;
          })
        }
      />
    </div>
  );
}
