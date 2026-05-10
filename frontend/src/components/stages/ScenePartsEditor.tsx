import { useState } from "react";
import type {
  AbstractScene,
  PartReference,
  SceneParts,
  StickerPart,
  LowerThirdPart,
} from "../../types";
import { useCategoryEntries, type PartEntry } from "../../hooks/usePartCatalog";

/**
 * Stage 1 の SceneEditor から呼ばれる scene_parts editor。
 *
 * 対象フィールド (= renderPlan.ts の ScenePartsBundle と整合):
 *   - subtitle_style (= scene 内全 chunk に適用される字幕スタイル)
 *   - camera_move    (= 動画レイヤを wrap する transform)
 *   - frame_layout   (= 動画レイヤを wrap する framing)
 *   - transition_in / transition_out (= scene 境界 effect)
 *   - lower_third    (= 1 件、at + duration 必須)
 *   - stickers       (= 配列、各 entry に at + duration?)
 *   - sfx            (= 配列、本コンポーネントでは UI 未対応 = JSON 直編集)
 *
 * params の細かい個別編集 UI は提供しない (= yaml の default が使われる)。
 * 高度な params カスタマイズは旧来通り JSON 直編集で対応する。
 *
 * 設計 ref: docs/plannings/2026-05-10_compositional-architecture.md §4
 */
export function ScenePartsEditor({
  scene,
  onSceneChange,
}: {
  scene: AbstractScene;
  onSceneChange: (fn: (s: AbstractScene) => AbstractScene) => void;
}) {
  const [open, setOpen] = useState(false);
  const subtitleEntries = useCategoryEntries("subtitle_styles");
  const cameraEntries = useCategoryEntries("camera_moves");
  const frameLayoutEntries = useCategoryEntries("frame_layouts");
  const transitionEntries = useCategoryEntries("transitions");
  const lowerThirdEntries = useCategoryEntries("lower_thirds");
  const stickerEntries = useCategoryEntries("stickers");

  const sp = scene.scene_parts ?? {};
  const updateSP = (mut: (next: SceneParts) => void) => {
    onSceneChange((s) => {
      const next: SceneParts = JSON.parse(JSON.stringify(s.scene_parts ?? {}));
      mut(next);
      return { ...s, scene_parts: next };
    });
  };
  const totalConfigured = countConfigured(sp);

  return (
    <div className="bg-slate-800/40 rounded p-2 text-xs">
      <button
        type="button"
        className="flex items-center gap-1 w-full text-left hover:text-emerald-300"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-slate-400 font-mono">{open ? "▼" : "▶"}</span>
        <span className="text-slate-500">🎨 演出パーツ</span>
        <span className="text-slate-500">({totalConfigured} 件設定済み)</span>
      </button>
      {open && (
        <div className="mt-2 space-y-2 pl-2 border-l-2 border-slate-700">
          <SinglePartRow
            label="字幕スタイル"
            field="subtitle_style"
            entries={subtitleEntries}
            value={sp.subtitle_style}
            onChange={(ref) =>
              updateSP((next) => {
                if (ref) next.subtitle_style = ref;
                else delete next.subtitle_style;
              })
            }
          />
          <SinglePartRow
            label="カメラ動き"
            field="camera_move"
            entries={cameraEntries}
            value={sp.camera_move}
            onChange={(ref) =>
              updateSP((next) => {
                if (ref) next.camera_move = ref;
                else delete next.camera_move;
              })
            }
          />
          <SinglePartRow
            label="フレーム配置"
            field="frame_layout"
            entries={frameLayoutEntries}
            value={sp.frame_layout}
            onChange={(ref) =>
              updateSP((next) => {
                if (ref) next.frame_layout = ref;
                else delete next.frame_layout;
              })
            }
          />
          <SinglePartRow
            label="冒頭 transition"
            field="transition_in"
            entries={transitionEntries}
            value={sp.transition_in}
            onChange={(ref) =>
              updateSP((next) => {
                if (ref) next.transition_in = ref;
                else delete next.transition_in;
              })
            }
          />
          <SinglePartRow
            label="末尾 transition"
            field="transition_out"
            entries={transitionEntries}
            value={sp.transition_out}
            onChange={(ref) =>
              updateSP((next) => {
                if (ref) next.transition_out = ref;
                else delete next.transition_out;
              })
            }
          />

          <LowerThirdRow
            entries={lowerThirdEntries}
            value={sp.lower_third}
            onChange={(lt) =>
              updateSP((next) => {
                if (lt) next.lower_third = lt;
                else delete next.lower_third;
              })
            }
          />

          <StickersRow
            entries={stickerEntries}
            value={sp.stickers ?? []}
            onChange={(arr) =>
              updateSP((next) => {
                if (arr.length > 0) next.stickers = arr;
                else delete next.stickers;
              })
            }
          />
        </div>
      )}
    </div>
  );
}

function countConfigured(sp: SceneParts): number {
  let n = 0;
  if (sp.subtitle_style) n++;
  if (sp.camera_move) n++;
  if (sp.frame_layout) n++;
  if (sp.transition_in) n++;
  if (sp.transition_out) n++;
  if (sp.lower_third) n++;
  if ((sp.stickers ?? []).length > 0) n++;
  if ((sp.sfx ?? []).length > 0) n++;
  return n;
}

// ─── 単一参照の dropdown 選択 (= subtitle_style / camera_move / ...) ───
function SinglePartRow({
  label,
  field,
  entries,
  value,
  onChange,
}: {
  label: string;
  field: string;
  entries: PartEntry[];
  value: PartReference | undefined;
  onChange: (ref: PartReference | null) => void;
}) {
  const currentEntry = value
    ? entries.find((e) => e.id === value.id)
    : undefined;
  return (
    <div className="flex items-center gap-2">
      <span className="text-slate-500 w-32 shrink-0" title={field}>
        {label}
      </span>
      <select
        className="select text-xs flex-1"
        value={value?.id ?? ""}
        onChange={(e) => {
          const v = e.target.value;
          if (!v) onChange(null);
          else onChange({ id: v, params: value?.params });
        }}
      >
        <option value="">(未設定)</option>
        {entries.map((entry) => (
          <option key={entry.id} value={entry.id}>
            {entry.id}
          </option>
        ))}
      </select>
      {currentEntry?.description && (
        <span
          className="text-[10px] text-slate-500 truncate max-w-[200px]"
          title={currentEntry.description}
        >
          {currentEntry.description.split("\n")[0]}
        </span>
      )}
    </div>
  );
}

// ─── lower_third (= id + at + duration) ───
function LowerThirdRow({
  entries,
  value,
  onChange,
}: {
  entries: PartEntry[];
  value: LowerThirdPart | undefined;
  onChange: (lt: LowerThirdPart | null) => void;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-slate-500 w-32 shrink-0">下部テロップ</span>
        <select
          className="select text-xs flex-1"
          value={value?.id ?? ""}
          onChange={(e) => {
            const v = e.target.value;
            if (!v) onChange(null);
            else
              onChange({
                id: v,
                at: value?.at ?? 0,
                duration: value?.duration ?? 3,
                params: value?.params,
              });
          }}
        >
          <option value="">(未設定)</option>
          {entries.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.id}
            </option>
          ))}
        </select>
      </div>
      {value && (
        <div className="flex items-center gap-2 pl-32 ml-2">
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            at
            <input
              type="number"
              step="0.1"
              min="0"
              className="input text-xs py-0 w-16"
              value={value.at}
              onChange={(e) =>
                onChange({ ...value, at: Number(e.target.value) || 0 })
              }
            />
          </label>
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            duration
            <input
              type="number"
              step="0.1"
              min="0.1"
              className="input text-xs py-0 w-16"
              value={value.duration}
              onChange={(e) =>
                onChange({
                  ...value,
                  duration: Math.max(0.1, Number(e.target.value)),
                })
              }
            />
          </label>
        </div>
      )}
    </div>
  );
}

// ─── stickers (= 配列、各 entry に id + at + duration?) ───
function StickersRow({
  entries,
  value,
  onChange,
}: {
  entries: PartEntry[];
  value: StickerPart[];
  onChange: (arr: StickerPart[]) => void;
}) {
  const addSticker = () => {
    if (entries.length === 0) return;
    onChange([...value, { id: entries[0].id, at: 0, duration: 1.5 }]);
  };
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-slate-500 w-32 shrink-0">
          ステッカー ({value.length})
        </span>
        <button
          type="button"
          className="btn-ghost text-[10px]"
          onClick={addSticker}
          disabled={entries.length === 0}
        >
          + 追加
        </button>
      </div>
      {value.map((sticker, i) => (
        <div key={i} className="flex items-center gap-2 pl-32 ml-2">
          <select
            className="select text-xs flex-1"
            value={sticker.id}
            onChange={(e) => {
              const next = [...value];
              next[i] = { ...sticker, id: e.target.value };
              onChange(next);
            }}
          >
            {entries.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.id}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            at
            <input
              type="number"
              step="0.1"
              min="0"
              className="input text-xs py-0 w-14"
              value={sticker.at}
              onChange={(e) => {
                const next = [...value];
                next[i] = { ...sticker, at: Number(e.target.value) || 0 };
                onChange(next);
              }}
            />
          </label>
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            dur
            <input
              type="number"
              step="0.1"
              min="0.1"
              className="input text-xs py-0 w-14"
              value={sticker.duration ?? 1.5}
              onChange={(e) => {
                const next = [...value];
                next[i] = {
                  ...sticker,
                  duration: Math.max(0.1, Number(e.target.value)),
                };
                onChange(next);
              }}
            />
          </label>
          <button
            type="button"
            className="text-rose-400 hover:text-rose-300 text-[12px]"
            title="このステッカーを削除"
            onClick={() => onChange(value.filter((_, j) => j !== i))}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
