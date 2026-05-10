import { useState } from "react";
import type {
  AbstractScreenplay,
  GlobalParts,
  GlobalPartsBgm,
  GlobalPartsCard,
  PartReference,
} from "../../types";
import { useCategoryEntries, type PartEntry } from "../../hooks/usePartCatalog";

/**
 * Stage 1 の screenplay-wide 設定エディタ。caption の直下あたりに置く想定。
 *
 * 対象フィールド (= renderPlan.ts の GlobalParts と整合):
 *   - filter_preset: screenplay 全体に被せる CSS filter (= warm/cool/monochrome 等)
 *   - intro_card / outro_card: 冒頭 / 末尾の N 秒 title card
 *   - bgm: 全長で流す BGM (= path + ducking_curve)
 *
 * sfx は scene 単位なので ScenePartsEditor 側で扱う (= 本コンポーネントには無い)。
 *
 * 設計 ref: docs/plannings/2026-05-10_compositional-architecture.md §4-5
 */
export function GlobalPartsEditor({
  abstract,
  onChange,
}: {
  abstract: AbstractScreenplay;
  onChange: (next: AbstractScreenplay) => void;
}) {
  const [open, setOpen] = useState(false);
  const filterEntries = useCategoryEntries("filter_presets");
  const titleCardEntries = useCategoryEntries("title_cards");

  const gp = abstract.global_parts ?? {};
  const updateGP = (mut: (next: GlobalParts) => void) => {
    const next: GlobalParts = JSON.parse(JSON.stringify(gp));
    mut(next);
    // 全部 undefined になったら global_parts キーごと削除 (= JSON 簡潔化)
    const nextHasAny =
      next.filter_preset || next.intro_card || next.outro_card || next.bgm;
    const nextSp = nextHasAny ? next : undefined;
    const cloned: AbstractScreenplay = { ...abstract };
    if (nextSp) cloned.global_parts = nextSp;
    else delete cloned.global_parts;
    onChange(cloned);
  };

  const totalConfigured = countConfigured(gp);

  return (
    <div className="bg-slate-800/40 rounded p-2 text-xs">
      <button
        type="button"
        className="flex items-center gap-1 w-full text-left hover:text-emerald-300"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-slate-400 font-mono">{open ? "▼" : "▶"}</span>
        <span className="text-slate-500">
          🌐 動画全体の演出 (filter / intro / outro / BGM)
        </span>
        <span className="text-slate-500">({totalConfigured} 件設定済み)</span>
      </button>
      {open && (
        <div className="mt-2 space-y-3 pl-2 border-l-2 border-slate-700">
          <FilterPresetRow
            entries={filterEntries}
            value={gp.filter_preset}
            onChange={(ref) =>
              updateGP((next) => {
                if (ref) next.filter_preset = ref;
                else delete next.filter_preset;
              })
            }
          />

          <CardRow
            label="冒頭カード (intro_card)"
            entries={titleCardEntries}
            value={gp.intro_card}
            defaultDuration={1.5}
            onChange={(card) =>
              updateGP((next) => {
                if (card) next.intro_card = card;
                else delete next.intro_card;
              })
            }
          />

          <CardRow
            label="末尾カード (outro_card)"
            entries={titleCardEntries}
            value={gp.outro_card}
            defaultDuration={2.0}
            onChange={(card) =>
              updateGP((next) => {
                if (card) next.outro_card = card;
                else delete next.outro_card;
              })
            }
          />

          <BgmRow
            value={gp.bgm}
            onChange={(bgm) =>
              updateGP((next) => {
                if (bgm) next.bgm = bgm;
                else delete next.bgm;
              })
            }
          />
        </div>
      )}
    </div>
  );
}

function countConfigured(gp: GlobalParts): number {
  let n = 0;
  if (gp.filter_preset) n++;
  if (gp.intro_card) n++;
  if (gp.outro_card) n++;
  if (gp.bgm) n++;
  return n;
}

// ─── filter_preset (= 単一 dropdown) ───
function FilterPresetRow({
  entries,
  value,
  onChange,
}: {
  entries: PartEntry[];
  value: PartReference | undefined;
  onChange: (ref: PartReference | null) => void;
}) {
  const currentEntry = value
    ? entries.find((e) => e.id === value.id)
    : undefined;
  return (
    <div className="flex items-center gap-2">
      <span className="text-slate-500 w-44 shrink-0">フィルタ (色調)</span>
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

// ─── intro / outro card 共通 ───
function CardRow({
  label,
  entries,
  value,
  defaultDuration,
  onChange,
}: {
  label: string;
  entries: PartEntry[];
  value: GlobalPartsCard | undefined;
  defaultDuration: number;
  onChange: (card: GlobalPartsCard | null) => void;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-slate-500 w-44 shrink-0">{label}</span>
        <select
          className="select text-xs flex-1"
          value={value?.id ?? ""}
          onChange={(e) => {
            const v = e.target.value;
            if (!v) onChange(null);
            else
              onChange({
                id: v,
                duration_sec: value?.duration_sec ?? defaultDuration,
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
        <div className="flex items-center gap-2 pl-44 ml-2">
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            duration (秒)
            <input
              type="number"
              step="0.1"
              min="0.1"
              className="input text-xs py-0 w-16"
              value={value.duration_sec}
              onChange={(e) =>
                onChange({
                  ...value,
                  duration_sec: Math.max(0.1, Number(e.target.value)),
                })
              }
            />
          </label>
          <ParamsKvEditor
            params={value.params ?? {}}
            onChange={(params) => onChange({ ...value, params })}
            hint='例: {"text": "登録お願いします"}'
          />
        </div>
      )}
    </div>
  );
}

// ─── bgm (= path + ducking_curve scalar) ───
function BgmRow({
  value,
  onChange,
}: {
  value: GlobalPartsBgm | undefined;
  onChange: (bgm: GlobalPartsBgm | null) => void;
}) {
  const enabled = !!value;
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-slate-500 w-44 shrink-0">BGM</span>
        <button
          type="button"
          className={`btn-ghost text-[10px] ${enabled ? "text-rose-400" : "text-emerald-400"}`}
          onClick={() => {
            if (enabled) onChange(null);
            else onChange({ path: "", ducking_curve: 0.4 });
          }}
        >
          {enabled ? "削除" : "+ 設定"}
        </button>
      </div>
      {value && (
        <div className="space-y-1 pl-44 ml-2">
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            path
            <input
              type="text"
              className="input text-xs py-0 flex-1"
              placeholder="assets/bgm/upbeat.mp3 か http URL"
              value={value.path}
              onChange={(e) => onChange({ ...value, path: e.target.value })}
            />
          </label>
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            音量 (0-1、0.4 推奨)
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              className="input text-xs py-0 w-16"
              value={
                typeof value.ducking_curve === "number"
                  ? value.ducking_curve
                  : 0.4
              }
              onChange={(e) =>
                onChange({
                  ...value,
                  ducking_curve: Math.max(
                    0,
                    Math.min(1, Number(e.target.value)),
                  ),
                })
              }
            />
          </label>
        </div>
      )}
    </div>
  );
}

// ─── 簡易 params KV editor (= 任意の text 入力、JSON 1 行) ───
function ParamsKvEditor({
  params,
  onChange,
  hint,
}: {
  params: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  hint?: string;
}) {
  const [text, setText] = useState(() =>
    Object.keys(params).length === 0 ? "" : JSON.stringify(params),
  );
  const [err, setErr] = useState<string | null>(null);
  return (
    <label
      className="flex items-center gap-1 text-[10px] text-slate-500 flex-1"
      title={hint}
    >
      params
      <input
        type="text"
        className={`input text-xs py-0 flex-1 ${err ? "border-rose-500" : ""}`}
        placeholder={hint}
        value={text}
        onChange={(e) => {
          const v = e.target.value;
          setText(v);
          if (!v.trim()) {
            setErr(null);
            onChange({});
            return;
          }
          try {
            const parsed = JSON.parse(v);
            if (
              parsed &&
              typeof parsed === "object" &&
              !Array.isArray(parsed)
            ) {
              setErr(null);
              onChange(parsed as Record<string, unknown>);
            } else {
              setErr("object でない");
            }
          } catch (e) {
            setErr(String(e).split(":").slice(-1)[0].trim());
          }
        }}
      />
      {err && <span className="text-rose-400">{err}</span>}
    </label>
  );
}
