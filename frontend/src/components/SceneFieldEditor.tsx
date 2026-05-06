import { useEffect, useState } from "react";
import { api } from "../api";
import { useShellCtx } from "./StageGate";
import type { Scene } from "../types";

// 微修正したい項目のみ狙って patch_scene できる構造化エディタ。
// Stage 3 (背景) と Stage 4 (Kling) のシーンカード内で、ロケ / カメラ距離 /
// 動きの 3 つを inline 編集できる。長文 prompt の自由編集は廃止し、
// 構造化フィールドのみ編集 → compose で派生プロンプトが再生成される
// (= live derivation 維持)。

type EditableField = "location_ref" | "camera_distance" | "animation_style";

const CAMERA_OPTIONS = [
  { value: "close-up", label: "close-up (顔寄り)" },
  { value: "medium-close", label: "medium-close (胸〜顔)" },
  { value: "medium", label: "medium (腰〜顔)" },
  { value: "wide", label: "wide (全身)" },
] as const;

const ANIM_OPTIONS = [
  { value: "subtle", label: "subtle (控えめ)" },
  { value: "standard", label: "standard (標準)" },
  { value: "expressive", label: "expressive (派手)" },
] as const;

export default function SceneFieldEditor({
  scene,
  sIdx,
  fields,
}: {
  scene: Scene;
  sIdx: number;
  fields: EditableField[];
}) {
  const ctx = useShellCtx();
  const [locations, setLocations] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fields.includes("location_ref")) return;
    api
      .listLocations()
      .then((d) => setLocations(d.locations.map((l) => l.id)))
      .catch(() => {});
  }, [fields]);

  const onChange = async (field: EditableField, value: string | undefined) => {
    setSaving(true);
    setError(null);
    try {
      await api.patchScene(ctx.detail.timestamp, sIdx, {
        [field]: value || null,
      });
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px]">
      {fields.includes("location_ref") && (
        <label className="flex items-center gap-1">
          <span className="text-slate-500">背景</span>
          <select
            className="select text-[11px] py-0.5"
            value={scene.location_ref ?? ""}
            disabled={saving}
            onChange={(e) =>
              onChange("location_ref", e.target.value || undefined)
            }
          >
            <option value="">(未設定)</option>
            {locations.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
      )}
      {fields.includes("camera_distance") && (
        <label className="flex items-center gap-1">
          <span className="text-slate-500">カメラ</span>
          <select
            className="select text-[11px] py-0.5"
            value={scene.camera_distance ?? ""}
            disabled={saving}
            onChange={(e) =>
              onChange("camera_distance", e.target.value || undefined)
            }
          >
            <option value="">(ロケ既定)</option>
            {CAMERA_OPTIONS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      )}
      {fields.includes("animation_style") && (
        <label className="flex items-center gap-1">
          <span className="text-slate-500">動き</span>
          <select
            className="select text-[11px] py-0.5"
            value={scene.animation_style ?? ""}
            disabled={saving}
            onChange={(e) =>
              onChange("animation_style", e.target.value || undefined)
            }
          >
            <option value="">(既定: standard)</option>
            {ANIM_OPTIONS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
      )}
      {saving && <span className="text-amber-400 text-[10px]">保存中…</span>}
      {error && <span className="text-rose-400 text-[10px]">{error}</span>}
    </div>
  );
}
