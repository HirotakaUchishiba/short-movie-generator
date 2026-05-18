// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
//
// シーンの背景 (= location_ref) を選ぶ。analyze が pre-fill した値を初期表示し、
// ユーザが訂正できる。空選択で `(未設定)` (= completeness banner で警告)。

import type { AbstractScreenplay } from "../../types";

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
  const value = scene.location_ref ?? "";
  return (
    <label className="flex items-center gap-1">
      <span className="text-slate-500 shrink-0">🏠 背景</span>
      <select
        className="select text-xs flex-1"
        value={value}
        onChange={(e) => {
          const v = e.target.value;
          onSceneChange((s) => {
            const next = { ...s };
            if (v) {
              next.location_ref = v;
            } else {
              delete (next as Record<string, unknown>).location_ref;
            }
            return next;
          });
        }}
      >
        <option value="">(未設定)</option>
        {locationIds.map((id) => (
          <option key={id} value={id}>
            {id}
          </option>
        ))}
      </select>
    </label>
  );
}
