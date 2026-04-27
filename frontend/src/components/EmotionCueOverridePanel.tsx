import { useState } from "react";
import { api } from "../api";
import { useShellCtx } from "./StageGate";
import { usePresets } from "../usePresets";
import type { Scene } from "../types";

const CATEGORY_KEYS = [
  "facial",
  "eye_gaze",
  "hair",
  "body_posture",
  "lighting",
  "camera",
  "tone",
] as const;

// scene の dominant emotion を求める (line出現数で多数決、同数なら最初の出現順)
function dominantEmotion(scene: Scene): string | null {
  const counts: Record<string, number> = {};
  let firstOrder: string[] = [];
  for (const ln of scene.lines ?? []) {
    const e = ln.emotion;
    if (!e) continue;
    if (!(e in counts)) firstOrder.push(e);
    counts[e] = (counts[e] ?? 0) + 1;
  }
  if (firstOrder.length === 0) return null;
  return firstOrder.reduce((best, e) => (counts[e] > counts[best] ? e : best));
}

export default function EmotionCueOverridePanel({
  scene,
  sIdx,
}: {
  scene: Scene;
  sIdx: number;
}) {
  const ctx = useShellCtx();
  const { data: presets, error } = usePresets();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const overrides = scene.emotion_cue_overrides ?? {};

  if (error) {
    return (
      <div className="text-[10px] text-rose-400">preset取得失敗: {error}</div>
    );
  }

  if (!presets) {
    return (
      <div className="mt-2 text-[10px] text-slate-500">プリセット読込中...</div>
    );
  }

  const dom = dominantEmotion(scene);
  const emotionDefaults =
    (dom && presets.emotion_default_preset_ids[dom]) || {};

  const onChange = async (category: string, presetId: string) => {
    setSaving(true);
    try {
      const newOverrides = { ...overrides };
      if (presetId === "") {
        delete newOverrides[category];
      } else {
        newOverrides[category] = presetId;
      }
      await api.patchScene(ctx.detail.timestamp, sIdx, {
        emotion_cue_overrides:
          Object.keys(newOverrides).length === 0 ? null : newOverrides,
      });
      await ctx.reload();
    } catch (e) {
      alert(`override保存失敗: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const onTagToggle = async (tag: string) => {
    setSaving(true);
    try {
      const cur = scene.tags ?? [];
      const next = cur.includes(tag)
        ? cur.filter((t) => t !== tag)
        : [...cur, tag];
      await api.patchScene(ctx.detail.timestamp, sIdx, {
        tags: next.length === 0 ? null : next,
      });
      await ctx.reload();
    } catch (e) {
      alert(`tag保存失敗: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const numOverrides = Object.keys(overrides).length;

  return (
    <div className="mt-2 text-[10px]">
      <button
        type="button"
        className="text-slate-400 hover:text-slate-200"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "▼" : "▶"} 視覚演出オーバーライド ({numOverrides}/
        {CATEGORY_KEYS.length}カテゴリ上書き中)
      </button>
      {open && (
        <div className="mt-1 p-2 rounded bg-slate-950/70 border border-slate-800 space-y-2">
          {/* Tag chips */}
          <div>
            <div className="text-slate-500 mb-1">🏷️ タグ (scope解決用)</div>
            <div className="flex flex-wrap gap-1">
              {presets.scene_tags.map((tag) => {
                const active = (scene.tags ?? []).includes(tag);
                const labelJa = presets.scene_tag_labels_ja[tag] ?? tag;
                return (
                  <button
                    key={tag}
                    type="button"
                    disabled={saving}
                    onClick={() => onTagToggle(tag)}
                    title={tag}
                    className={
                      active
                        ? "px-1.5 py-0.5 rounded text-[10px] bg-emerald-700 text-emerald-100"
                        : "px-1.5 py-0.5 rounded text-[10px] bg-slate-800 text-slate-400 hover:bg-slate-700"
                    }
                  >
                    {labelJa}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Category overrides */}
          <div className="space-y-1">
            <div className="text-slate-500">
              🎭 カテゴリ別 preset 上書き
              {dom && (
                <span className="ml-2 text-emerald-300">
                  (現在の主要 emotion: {dom})
                </span>
              )}
            </div>
            {CATEGORY_KEYS.map((catKey) => {
              const lib = presets.libraries[catKey] ?? {};
              const labels = presets.labels_ja[catKey] ?? {};
              const current = overrides[catKey] ?? "";
              const emotionDefault = emotionDefaults[catKey];
              const catLabel = presets.category_labels_ja[catKey] ?? catKey;
              // dropdown が選択している ID。override 未設定なら emotion 既定があればそれ。
              const effective = current || emotionDefault || "";
              return (
                <div
                  key={catKey}
                  className="flex items-center gap-2 text-[11px]"
                >
                  <label
                    className="w-20 text-slate-400 flex-shrink-0"
                    title={catKey}
                  >
                    {catLabel}
                  </label>
                  <select
                    className="flex-1 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-[11px]"
                    value={effective}
                    disabled={saving}
                    onChange={(e) => onChange(catKey, e.target.value)}
                  >
                    <option value="">— 既定 (emotion由来) —</option>
                    {Object.keys(lib).map((id) => {
                      const ja = labels[id] ?? id;
                      const isEmotionDefault = id === emotionDefault;
                      return (
                        <option key={id} value={id} title={lib[id]}>
                          {ja}
                          {isEmotionDefault ? "  (emotion由来)" : ""}
                        </option>
                      );
                    })}
                  </select>
                  <span
                    className={
                      "text-[10px] w-12 text-right " +
                      (current ? "text-emerald-300" : "text-slate-500")
                    }
                    title={current ? "上書き中" : "既定値"}
                  >
                    {current ? "個別" : "既定"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
