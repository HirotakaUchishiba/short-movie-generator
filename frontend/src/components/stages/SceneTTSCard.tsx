// StageTTS.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 1 シーン分の TTS 操作カード:
//   - SceneTTSCard: シーンヘッダ + line 一覧
//   - LineTTSRow  : 1 line の試聴情報 + 編集トグル
//   - LineTextEditor: line.text を直接書き換える小型エディタ
//
// 3 つは parent → child の親子関係なので 1 file に同梱する (= 片方だけ
// import するシナリオが想定されない)。

import { useState } from "react";

import { api } from "../../api";
import type { CostMedianRate, Line, Scene, TtsPricing } from "../../types";
import { formatJpy, formatUsd, lineCost, sceneCost } from "../../tts-cost";
import { useShellCtx } from "../StageGate";

export function SceneTTSCard({
  scene,
  sIdx,
  pricing,
  rate,
}: {
  scene: Scene;
  sIdx: number;
  pricing: TtsPricing;
  rate: CostMedianRate | null;
}) {
  const lines = scene.lines ?? [];
  const cost = sceneCost(scene, pricing, rate);
  return (
    <div className="card">
      <div className="flex justify-between items-center mb-3">
        <h3 className="font-semibold">
          シーン{sIdx + 1}{" "}
          <span className="text-slate-400 text-sm font-normal">
            ({scene.duration}s · {lines.length}lines)
          </span>
        </h3>
        <span className="text-xs text-slate-400">
          このシーンの文字数 →{" "}
          <span className="text-emerald-300 font-mono">
            {formatUsd(cost.usd, 4)}
          </span>
          <span className="text-slate-500 ml-1">
            ({formatJpy(cost.jpy)} / {cost.credits} credits)
          </span>
        </span>
      </div>
      <div className="space-y-3">
        {lines.map((line, lIdx) => (
          <LineTTSRow
            key={line._uid ?? lIdx}
            line={line}
            sIdx={sIdx}
            lIdx={lIdx}
            pricing={pricing}
            rate={rate}
          />
        ))}
      </div>
    </div>
  );
}

function LineTTSRow({
  line,
  sIdx,
  lIdx,
  pricing,
  rate,
}: {
  line: Line;
  sIdx: number;
  lIdx: number;
  pricing: TtsPricing;
  rate: CostMedianRate | null;
}) {
  const [editing, setEditing] = useState(false);
  const cost = lineCost(line, pricing, rate);
  return (
    <div className="rounded border border-slate-700 bg-slate-900/40 p-3">
      <div className="flex justify-between items-start mb-2 gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium break-words">{line.text}</div>
          <div className="text-xs text-slate-400 mt-1">
            start={line.start}s{line.end != null && `, end=${line.end}s`}
            <span className="mx-1">·</span>
            {cost.chars}字 → {formatUsd(cost.usd, 5)}
          </div>
        </div>
        <div className="flex gap-2 items-center flex-shrink-0">
          <button
            className="btn-ghost text-xs"
            onClick={() => setEditing((v) => !v)}
          >
            {editing ? "閉じる" : "テキスト編集"}
          </button>
        </div>
      </div>
      {editing && (
        <LineTextEditor key={line.text} line={line} sIdx={sIdx} lIdx={lIdx} />
      )}
    </div>
  );
}

function LineTextEditor({
  line,
  sIdx,
  lIdx,
}: {
  line: Line;
  sIdx: number;
  lIdx: number;
}) {
  const ctx = useShellCtx();
  const [draft, setDraft] = useState(line.text);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSave = async (alsoRegen: boolean) => {
    setSaving(true);
    setError(null);
    try {
      await api.patchLine(ctx.detail.timestamp, sIdx, lIdx, { text: draft });
      await ctx.reload();
      if (alsoRegen) {
        await ctx.regen({ stage: "tts", force: true });
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const dirty = draft !== line.text;

  return (
    <div className="mt-3 border-t border-slate-700 pt-3 space-y-2">
      {error && <div className="text-rose-400 text-xs">{error}</div>}
      <div>
        <div className="label">
          line.text
          <span className="ml-2 text-[10px] text-slate-500">
            このテキストがそのまま TTS
            へ送られます。読み間違いがあれば直接書き換え (例: "200万" →
            "二百万")
          </span>
        </div>
        <textarea
          className="input font-mono text-sm h-20"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <button
          className="btn-ghost text-xs"
          onClick={() => setDraft(line.text)}
          disabled={!dirty || saving}
        >
          元に戻す
        </button>
        <button
          className="btn-secondary"
          disabled={!dirty || saving}
          onClick={() => onSave(false)}
        >
          台本に保存のみ
        </button>
        <button
          className="btn-primary"
          disabled={!dirty || saving}
          onClick={() => onSave(true)}
        >
          {saving ? "..." : "保存して全シーンTTS再生成"}
        </button>
      </div>
    </div>
  );
}
