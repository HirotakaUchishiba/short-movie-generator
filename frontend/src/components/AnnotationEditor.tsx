import type { Annotation } from "../types";
import {
  useCategoryEntries,
  useCategoryStatus,
  type PartEntry,
} from "../hooks/usePartCatalog";

/**
 * per-scene の annotation (= clip_library soft rank メタ) を編集する UI。
 *
 * 設計 ref: docs/plannings/2026-05-10_full-conformance-roadmap.md §10.2 (Phase C4)
 *
 * 全 field optional。1 field でも書かれていれば onChange(annotation)、全部空なら
 * onChange(undefined) を呼ぶ。
 *
 * visual_intent_id は config/part_registry/visual_intents.yaml から enum 選択。
 * 選択中の intent の `valid_start_emotions` は互換性ヒントとしてツールチップ表示。
 */
export function AnnotationEditor({
  annotation,
  onChange,
}: {
  annotation?: Annotation;
  onChange: (next: Annotation | undefined) => void;
}) {
  const intents = useCategoryEntries("visual_intents");
  const intentStatus = useCategoryStatus("visual_intents");
  const loading = intentStatus === null;

  const cur: Annotation = annotation ?? {};

  const update = (mut: (a: Annotation) => void) => {
    const next: Annotation = { ...cur };
    mut(next);
    // 全 field 空なら undefined を渡し、scene["annotation"] ごと削除させる
    const hasAny =
      next.visual_intent_id != null ||
      next.duration_bucket != null ||
      next.motion_intensity != null ||
      next.generation_seed != null;
    onChange(hasAny ? next : undefined);
  };

  const selectedIntent = cur.visual_intent_id
    ? intents.find((e) => e.id === cur.visual_intent_id)
    : undefined;

  return (
    <div className="bg-slate-800/40 rounded p-2 text-xs space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-slate-300 font-medium">
          📝 annotation (clip_library soft rank)
        </span>
        <span className="text-[10px] text-slate-500">
          (全 field optional、互換 fallback あり)
        </span>
      </div>

      {loading ? (
        <div className="text-slate-500 text-[11px]">
          visual_intents catalog 読込中…
        </div>
      ) : (
        <div className="space-y-1.5">
          <VisualIntentRow
            entries={intents}
            value={cur.visual_intent_id}
            onChange={(id) =>
              update((a) => {
                if (id) a.visual_intent_id = id;
                else delete a.visual_intent_id;
              })
            }
            selectedEntry={selectedIntent}
          />

          <label className="flex items-center gap-2">
            <span className="text-slate-500 w-32 shrink-0">
              duration_bucket
            </span>
            <select
              className="select text-xs flex-1"
              value={cur.duration_bucket ?? ""}
              onChange={(e) =>
                update((a) => {
                  const v = e.target.value;
                  if (v === "5" || v === "10") {
                    a.duration_bucket = Number(v) as 5 | 10;
                  } else {
                    delete a.duration_bucket;
                  }
                })
              }
            >
              <option value="">(未設定)</option>
              <option value="5">5</option>
              <option value="10">10</option>
            </select>
          </label>

          <label className="flex items-center gap-2">
            <span className="text-slate-500 w-32 shrink-0">
              motion_intensity
            </span>
            <select
              className="select text-xs flex-1"
              value={cur.motion_intensity ?? ""}
              onChange={(e) =>
                update((a) => {
                  const v = e.target.value;
                  if (v === "low" || v === "medium" || v === "high") {
                    a.motion_intensity = v;
                  } else {
                    delete a.motion_intensity;
                  }
                })
              }
            >
              <option value="">(未設定)</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </label>
        </div>
      )}
    </div>
  );
}

function VisualIntentRow({
  entries,
  value,
  onChange,
  selectedEntry,
}: {
  entries: PartEntry[];
  value: string | undefined;
  onChange: (id: string | null) => void;
  selectedEntry: PartEntry | undefined;
}) {
  // valid_start_emotions ツールチップ (= intent と scene の start_emotion 整合性ヒント)
  const tooltip =
    selectedEntry?.valid_start_emotions &&
    selectedEntry.valid_start_emotions.length > 0
      ? `valid_start_emotions: ${selectedEntry.valid_start_emotions.join(", ")}`
      : undefined;
  return (
    <label className="flex items-center gap-2">
      <span className="text-slate-500 w-32 shrink-0">visual_intent_id</span>
      <select
        className="select text-xs flex-1"
        value={value ?? ""}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v ? v : null);
        }}
      >
        <option value="">(未設定)</option>
        {entries.map((entry) => (
          <option key={entry.id} value={entry.id}>
            {entry.id}
          </option>
        ))}
      </select>
      {tooltip && (
        <span
          className="text-[10px] text-slate-500 truncate max-w-[200px]"
          title={tooltip}
        >
          ℹ️ {tooltip}
        </span>
      )}
    </label>
  );
}
