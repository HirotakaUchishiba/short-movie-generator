import { useEffect, useState } from "react";
import type { CameraDistance, Identity } from "../types";
import { api } from "../api";

/**
 * per-scene の identity (= clip_library hard match キー) を編集する UI。
 *
 * 設計 ref: docs/plannings/2026-05-10_full-conformance-roadmap.md §10.2 (Phase C4)
 *
 * 4 fields (character_refs / location_ref / start_emotion / camera_distance) が
 * すべて揃ったときに `onChange(identity)` を呼ぶ。1 つでも欠ければ
 * `onChange(undefined)` を呼び、scene["identity"] が undefined となる
 * (= cold path = AI 生成 = clip_library hit せず)。
 *
 * リセットボタンで identity を完全に削除できる。
 */
export function IdentityEditor({
  identity,
  onChange,
}: {
  identity?: Identity;
  onChange: (next: Identity | undefined) => void;
}) {
  const [characterRefs, setCharacterRefs] = useState<string[]>([]);
  const [locationIds, setLocationIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listCharacters(), api.listLocations()])
      .then(([chars, locs]) => {
        if (cancelled) return;
        setCharacterRefs(chars.characters);
        setLocationIds(locs.locations.map((l) => l.id));
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 部分編集中の draft state。各 field を編集するたびに、4 fields 揃っているか
  // チェックして揃っていれば onChange(identity)、欠けていれば onChange(undefined)
  // を呼ぶ。
  const [draft, setDraft] = useState<Partial<Identity>>(() => identity ?? {});

  useEffect(() => {
    setDraft(identity ?? {});
  }, [identity]);

  const isComplete = (d: Partial<Identity>): d is Identity =>
    Array.isArray(d.character_refs) &&
    d.character_refs.length > 0 &&
    typeof d.location_ref === "string" &&
    d.location_ref.length > 0 &&
    typeof d.start_emotion === "string" &&
    d.start_emotion.length > 0 &&
    typeof d.camera_distance === "string" &&
    d.camera_distance.length > 0;

  const updateDraft = (mut: (d: Partial<Identity>) => void) => {
    const next = { ...draft };
    mut(next);
    setDraft(next);
    if (isComplete(next)) onChange(next);
    else onChange(undefined);
  };

  const reset = () => {
    setDraft({});
    onChange(undefined);
  };

  const complete = isComplete(draft);

  return (
    <div className="bg-slate-800/40 rounded p-2 text-xs space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-slate-300 font-medium">
          🆔 identity (clip_library hard match キー)
        </span>
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded ${
            complete
              ? "bg-emerald-700/40 text-emerald-200"
              : "bg-amber-700/40 text-amber-200"
          }`}
        >
          {complete ? "完全" : "不完全"}
        </span>
        <button
          type="button"
          className="ml-auto text-[10px] text-slate-500 hover:text-rose-300"
          onClick={reset}
          title="identity を削除 (= cold path で生成)"
        >
          ⤺ リセット
        </button>
      </div>

      {!complete && (
        <div className="text-[11px] text-amber-200">
          ⚠️ identity 不完全 (= clip_library hit が発動しない)
        </div>
      )}

      <div className="space-y-1.5">
        <CharacterRefsRow
          options={characterRefs}
          loading={loading}
          value={draft.character_refs ?? []}
          onChange={(refs) =>
            updateDraft((d) => {
              if (refs.length > 0) d.character_refs = refs;
              else delete d.character_refs;
            })
          }
        />

        <SelectRow
          label="location_ref"
          options={locationIds}
          loading={loading}
          value={draft.location_ref ?? ""}
          onChange={(v) =>
            updateDraft((d) => {
              if (v) d.location_ref = v;
              else delete d.location_ref;
            })
          }
        />

        <label className="flex items-center gap-2">
          <span className="text-slate-500 w-32 shrink-0">start_emotion</span>
          <select
            className="select text-xs flex-1"
            value={draft.start_emotion ?? ""}
            onChange={(e) =>
              updateDraft((d) => {
                const v = e.target.value;
                if (v) d.start_emotion = v;
                else delete d.start_emotion;
              })
            }
          >
            <option value="">(未設定)</option>
            {EMOTIONS.map((em) => (
              <option key={em} value={em}>
                {em}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2">
          <span className="text-slate-500 w-32 shrink-0">camera_distance</span>
          <select
            className="select text-xs flex-1"
            value={draft.camera_distance ?? ""}
            onChange={(e) =>
              updateDraft((d) => {
                const v = e.target.value as CameraDistance | "";
                if (v) d.camera_distance = v;
                else delete d.camera_distance;
              })
            }
          >
            <option value="">(未設定)</option>
            {CAMERA_DISTANCES.map((cd) => (
              <option key={cd} value={cd}>
                {cd}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}

const EMOTIONS = [
  "驚き",
  "喜び",
  "焦り",
  "落胆",
  "中立",
  "満足",
  "困惑",
  "怒り",
  "恥ずかしさ",
];

const CAMERA_DISTANCES: CameraDistance[] = [
  "close-up",
  "medium-close",
  "medium",
  "wide",
];

function SelectRow({
  label,
  options,
  loading,
  value,
  onChange,
}: {
  label: string;
  options: string[];
  loading: boolean;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="text-slate-500 w-32 shrink-0">{label}</span>
      <select
        className="select text-xs flex-1"
        value={value}
        disabled={loading}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{loading ? "読込中…" : "(未設定)"}</option>
        {options.map((id) => (
          <option key={id} value={id}>
            {id}
          </option>
        ))}
      </select>
    </label>
  );
}

function CharacterRefsRow({
  options,
  loading,
  value,
  onChange,
}: {
  options: string[];
  loading: boolean;
  value: string[];
  onChange: (refs: string[]) => void;
}) {
  const toggle = (ref: string) => {
    if (value.includes(ref)) onChange(value.filter((r) => r !== ref));
    else onChange([...value, ref]);
  };
  return (
    <div className="flex items-start gap-2">
      <span className="text-slate-500 w-32 shrink-0 pt-0.5">
        character_refs
      </span>
      <div className="flex-1 flex flex-wrap gap-1">
        {loading && <span className="text-slate-500">読込中…</span>}
        {!loading && options.length === 0 && (
          <span className="text-slate-500">(候補なし)</span>
        )}
        {!loading &&
          options.map((ref) => {
            const active = value.includes(ref);
            return (
              <button
                key={ref}
                type="button"
                className={`text-[10px] px-1.5 py-0.5 rounded border ${
                  active
                    ? "bg-emerald-700/40 border-emerald-500 text-emerald-100"
                    : "bg-slate-900/40 border-slate-700 text-slate-400 hover:text-slate-200"
                }`}
                onClick={() => toggle(ref)}
                title={active ? `${ref} を解除` : `${ref} を追加`}
              >
                {ref}
              </button>
            );
          })}
      </div>
    </div>
  );
}
