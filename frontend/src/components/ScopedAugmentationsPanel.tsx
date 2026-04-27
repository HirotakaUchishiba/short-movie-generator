import { useState } from "react";
import { api } from "../api";
import { useShellCtx } from "./StageGate";
import { usePresets, type PresetData } from "../usePresets";
import type { ScopedAugmentation } from "../types";

// プロジェクト全体の横断適用ルール (scoped_augmentations) 編集パネル。
// 同一 scope.tag を持つシーン群に scene_element preset をまとめて挿入する。
export default function ScopedAugmentationsPanel() {
  const ctx = useShellCtx();
  const { data: presets, error } = usePresets();
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);

  const augs = ctx.detail.screenplay.scoped_augmentations ?? [];

  if (error) return null;
  if (!presets) return null;

  const save = async (next: ScopedAugmentation[]) => {
    setSaving(true);
    try {
      await api.patchScreenplayMeta(ctx.detail.timestamp, {
        scoped_augmentations: next.length === 0 ? null : next,
      });
      await ctx.reload();
    } catch (e) {
      alert(`横断ルール保存失敗: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const addRule = async (rule: ScopedAugmentation) => {
    await save([...augs, { ...rule, id: `aug_${Date.now().toString(36)}` }]);
    setAdding(false);
  };

  const updateRule = async (
    idx: number,
    patch: Partial<ScopedAugmentation>,
  ) => {
    const next = augs.map((a, i) => (i === idx ? { ...a, ...patch } : a));
    await save(next);
  };

  const deleteRule = async (idx: number) => {
    const next = augs.filter((_, i) => i !== idx);
    await save(next);
  };

  const sceneTagCounts = (() => {
    const counts: Record<string, number> = {};
    for (const s of ctx.detail.screenplay.scenes) {
      for (const t of s.tags ?? []) counts[t] = (counts[t] ?? 0) + 1;
    }
    return counts;
  })();

  return (
    <div className="card border-purple-700/40 bg-purple-900/10 mt-4">
      <div className="flex items-center justify-between mb-2">
        <div>
          <h3 className="font-semibold text-purple-200">
            🎯 横断適用ルール (scoped augmentations)
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            scope.tag が一致する全シーンに scene_element プリセットを挿入。 BG /
            Kling 両方に反映されます。
          </p>
        </div>
        <button
          className="btn-ghost text-xs"
          disabled={saving}
          onClick={() => setAdding(true)}
        >
          + ルール追加
        </button>
      </div>

      {augs.length === 0 && !adding && (
        <p className="text-xs text-slate-500">ルール未設定</p>
      )}

      <div className="space-y-2">
        {augs.map((aug, i) => (
          <RuleRow
            key={aug.id ?? i}
            aug={aug}
            saving={saving}
            presets={presets}
            sceneTagCounts={sceneTagCounts}
            onUpdate={(patch) => updateRule(i, patch)}
            onDelete={() => deleteRule(i)}
          />
        ))}
        {adding && (
          <RuleEditor
            saving={saving}
            presets={presets}
            sceneTagCounts={sceneTagCounts}
            onSubmit={addRule}
            onCancel={() => setAdding(false)}
          />
        )}
      </div>
    </div>
  );
}

function RuleRow({
  aug,
  saving,
  presets,
  sceneTagCounts,
  onUpdate,
  onDelete,
}: {
  aug: ScopedAugmentation;
  saving: boolean;
  presets: PresetData;
  sceneTagCounts: Record<string, number>;
  onUpdate: (patch: Partial<ScopedAugmentation>) => void;
  onDelete: () => void;
}) {
  const elementsLib = presets.libraries.scene_element ?? {};
  const elementLabels = presets.labels_ja.scene_element ?? {};
  const tagLabel = aug.scope.tag
    ? (presets.scene_tag_labels_ja[aug.scope.tag] ?? aug.scope.tag)
    : "";
  const matchCount = aug.scope.tag
    ? (sceneTagCounts[aug.scope.tag] ?? 0)
    : (aug.scope.scene_idx?.length ?? 0);

  const removeElement = (id: string) =>
    onUpdate({ elements: aug.elements.filter((e) => e !== id) });

  const addElement = (id: string) => {
    if (aug.elements.includes(id)) return;
    onUpdate({ elements: [...aug.elements, id] });
  };

  const remaining = Object.keys(elementsLib).filter(
    (id) => !aug.elements.includes(id),
  );

  return (
    <div className="rounded border border-slate-700 bg-slate-900/50 p-2 text-xs">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div>
          適用範囲:{" "}
          <span className="text-purple-300">
            {aug.scope.tag
              ? `${tagLabel} (タグ)`
              : `シーン ${(aug.scope.scene_idx ?? []).map((i) => i + 1).join(", ")}`}
          </span>
          <span className="ml-2 text-slate-500">
            (対象 {matchCount} シーン)
          </span>
        </div>
        <button
          className="btn-ghost text-[10px] text-rose-300"
          disabled={saving}
          onClick={onDelete}
        >
          削除
        </button>
      </div>
      <div className="flex flex-wrap gap-1 items-center">
        <span className="text-slate-500">要素:</span>
        {aug.elements.map((id) => (
          <button
            key={id}
            type="button"
            className="px-1.5 py-0.5 rounded bg-purple-700/60 text-purple-100 text-[10px] hover:bg-rose-700"
            disabled={saving}
            title={`削除 (${elementsLib[id] ?? ""})`}
            onClick={() => removeElement(id)}
          >
            {elementLabels[id] ?? id} ✕
          </button>
        ))}
        {remaining.length > 0 && (
          <select
            className="bg-slate-800 border border-slate-700 rounded px-1 py-0.5 text-[10px]"
            disabled={saving}
            value=""
            onChange={(e) => {
              if (e.target.value) addElement(e.target.value);
            }}
          >
            <option value="">+ 追加</option>
            {remaining.map((id) => (
              <option key={id} value={id} title={elementsLib[id]}>
                {elementLabels[id] ?? id}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}

function RuleEditor({
  saving,
  presets,
  sceneTagCounts,
  onSubmit,
  onCancel,
}: {
  saving: boolean;
  presets: PresetData;
  sceneTagCounts: Record<string, number>;
  onSubmit: (rule: ScopedAugmentation) => void;
  onCancel: () => void;
}) {
  const [tag, setTag] = useState("");
  const [elements, setElements] = useState<string[]>([]);
  const elementsLib = presets.libraries.scene_element ?? {};
  const elementLabels = presets.labels_ja.scene_element ?? {};

  const matchCount = tag ? (sceneTagCounts[tag] ?? 0) : 0;
  const submit = () => {
    if (!tag || elements.length === 0) return;
    onSubmit({ scope: { tag }, elements });
  };

  return (
    <div className="rounded border border-purple-700 bg-purple-900/20 p-2 text-xs space-y-2">
      <div>
        <label className="text-slate-400 mr-2">適用範囲 (タグ):</label>
        <select
          className="bg-slate-800 border border-slate-700 rounded px-1 py-0.5"
          value={tag}
          onChange={(e) => setTag(e.target.value)}
        >
          <option value="">-- タグを選択 --</option>
          {presets.scene_tags.map((t) => {
            const ja = presets.scene_tag_labels_ja[t] ?? t;
            return (
              <option key={t} value={t}>
                {ja} ({sceneTagCounts[t] ?? 0}シーン)
              </option>
            );
          })}
        </select>
        {tag && (
          <span className="ml-2 text-slate-500">
            対象シーン数: {matchCount}
          </span>
        )}
      </div>
      <div>
        <label className="text-slate-400 mr-2">追加する要素:</label>
        <div className="inline-flex flex-wrap gap-1 items-center">
          {elements.map((id) => (
            <button
              key={id}
              type="button"
              className="px-1.5 py-0.5 rounded bg-purple-700/60 text-purple-100 text-[10px]"
              title={elementsLib[id] ?? ""}
              onClick={() => setElements((es) => es.filter((e) => e !== id))}
            >
              {elementLabels[id] ?? id} ✕
            </button>
          ))}
          <select
            className="bg-slate-800 border border-slate-700 rounded px-1 py-0.5 text-[10px]"
            value=""
            onChange={(e) => {
              if (!e.target.value) return;
              if (elements.includes(e.target.value)) return;
              setElements((es) => [...es, e.target.value]);
            }}
          >
            <option value="">+ 要素追加</option>
            {Object.entries(elementsLib)
              .filter(([id]) => !elements.includes(id))
              .map(([id, text]) => (
                <option key={id} value={id} title={text}>
                  {elementLabels[id] ?? id}
                </option>
              ))}
          </select>
        </div>
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <button className="btn-ghost text-xs" onClick={onCancel}>
          キャンセル
        </button>
        <button
          className="btn-primary text-xs"
          disabled={saving || !tag || elements.length === 0}
          onClick={submit}
        >
          追加
        </button>
      </div>
    </div>
  );
}
