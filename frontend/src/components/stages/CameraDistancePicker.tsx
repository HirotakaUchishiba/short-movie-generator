// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
//
// シーンのカメラ距離 (= camera_distance) を選ぶ。analyze が pre-fill した値を
// 初期表示し、ユーザが訂正できる。空選択は `_derive_identity` の fallback
// (= ロケ既定 → "medium-close") に委ねる。

import type { AbstractScreenplay } from "../../types";
import { CAMERA_DISTANCE_OPTIONS } from "./script-edit-utils";

export function CameraDistancePicker({
  scene,
  onSceneChange,
}: {
  scene: AbstractScreenplay["scenes"][number];
  onSceneChange: (
    fn: (
      s: AbstractScreenplay["scenes"][number],
    ) => AbstractScreenplay["scenes"][number],
  ) => void;
}) {
  const value = scene.camera_distance ?? "";
  return (
    <label className="flex items-center gap-1">
      <span className="text-slate-500 shrink-0">🎥 距離</span>
      <select
        className="select text-xs flex-1"
        value={value}
        onChange={(e) => {
          const v = e.target.value;
          onSceneChange((s) => {
            const next = { ...s };
            if (v) {
              next.camera_distance = v as NonNullable<
                typeof next.camera_distance
              >;
            } else {
              delete (next as Record<string, unknown>).camera_distance;
            }
            return next;
          });
        }}
      >
        <option value="">(自動: ロケ既定)</option>
        {CAMERA_DISTANCE_OPTIONS.map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </select>
    </label>
  );
}
