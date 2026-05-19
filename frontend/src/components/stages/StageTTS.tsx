import { useEffect, useMemo, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { ttsMergedAssetUrl, api } from "../../api";
import type { CostMedianRate, Line, Scene, TtsPricing } from "../../types";
import { useCostMedianRate } from "../../useCostMedianRate";
import {
  type CostBreakdown,
  formatJpy,
  formatUsd,
  lineCost,
  sceneCost,
  screenplayCost,
} from "../../tts-cost";
import { ModelSelector, SilenceControl, SpeedControl } from "./TtsControls";
import { modelMeta } from "./tts-utils";
// シーン境界編集は Stage 1 (ScriptEditPanel) に移動済み。Stage 2 では扱わない。

export default function StageTTS() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const { rate } = useCostMedianRate("tts", ctx.serverConfig.cost_models.tts);
  const totalCost = useMemo(
    () => screenplayCost(sp.scenes, ctx.serverConfig.tts_pricing, rate),
    [sp.scenes, ctx.serverConfig.tts_pricing, rate],
  );

  return (
    <StageGate
      stage="tts"
      title="TTS音声の生成"
      description="screenplay全体を1 API call で生成。line.audio_tags があれば ElevenLabs V3 inline tag として注入。各lineの再生成は不可、全体まとめての再生成のみ。"
      needsRunFirst
    >
      <PricingBanner
        pricing={ctx.serverConfig.tts_pricing}
        totalCost={totalCost}
      />
      <TtsSourcePreview />
      <BulkRegenBar totalCost={totalCost} />
      <MergedTTSPlayer />
      <div className="space-y-6 mt-4">
        {sp.scenes.map((scene, sIdx) => (
          <SceneTTSCard
            key={scene._uid ?? sIdx}
            scene={scene}
            sIdx={sIdx}
            pricing={ctx.serverConfig.tts_pricing}
            rate={rate}
          />
        ))}
      </div>
    </StageGate>
  );
}
// コスト計算 (= lineCost / sceneCost / screenplayCost / formatUsd / formatJpy)
// は ../../tts-cost.ts に抽出済み (= §5-c)。

// ─────────────────────────────────────────────────────────
// 価格バナー
// ─────────────────────────────────────────────────────────

function PricingBanner({
  pricing,
  totalCost,
}: {
  pricing: TtsPricing;
  totalCost: CostBreakdown;
}) {
  const meta = modelMeta(pricing.model);
  return (
    <div className="card border-emerald-700/40 bg-emerald-900/10">
      <div className="flex flex-wrap items-stretch gap-4">
        <div
          className={`rounded-md border px-4 py-3 flex flex-col justify-center min-w-[280px] ${meta.color}`}
        >
          <div className="text-[10px] uppercase tracking-wider opacity-70">
            使用中のモデル
          </div>
          <ModelSelector pricing={pricing} />
          <div className="flex gap-2 mt-1.5 text-[11px]">
            <span className="badge bg-black/30">
              文字単価 ×{pricing.credit_multiplier}
            </span>
            <span className="badge bg-black/30">{meta.contextLabel}</span>
            <span className="badge bg-black/30">{meta.qualityLabel}</span>
          </div>
        </div>
        <div className="flex-1 flex items-center justify-end gap-4 flex-wrap">
          <Stat label="全文字数" value={`${totalCost.chars} 字`} />
          <Stat
            label="credits"
            value={`${totalCost.credits.toLocaleString()}`}
          />
          <Stat label="全シーン1回生成" value={formatUsd(totalCost.usd, 3)} />
          <Stat label="(円換算)" value={formatJpy(totalCost.jpy)} />
        </div>
      </div>
      <SpeedControl key={pricing.global_speed} pricing={pricing} />
      <SilenceControl
        key={`${pricing.trim_silences}|${pricing.max_silence_ms}`}
        pricing={pricing}
      />
    </div>
  );
}

// SpeedControl / SilenceControl / ModelSelector は ./TtsControls.tsx に移管済。
// modelMeta は ./tts-utils.ts に移管済 (= §3.1.3)。

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-semibold">{value}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// 全シーン一括生成バー
// ─────────────────────────────────────────────────────────

function BulkRegenBar({ totalCost }: { totalCost: CostBreakdown }) {
  const ctx = useShellCtx();
  const [confirming, setConfirming] = useState(false);
  const running = ctx.jobStatus?.status === "running";

  const onForceRegen = async () => {
    setConfirming(false);
    await ctx.regen({ stage: "tts", force: true });
  };

  // パディングのみ反映: tts_full.mp3 を保持して per-line 切出しのみ再実行 (無料)。
  // text/voice/native_speed が変わっていれば cache miss になり自動で API 再呼出しに昇格する。
  const onApplyPaddingOnly = async () => {
    await ctx.regen({ stage: "tts", force: false });
  };

  return (
    <div className="card border-amber-700/40 bg-amber-900/10 mt-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">全シーンTTSを一括再生成</h3>
          <p className="text-xs text-slate-400 mt-1">
            screenplay の全 line.text を半角スペース×2で連結し、1 API call
            で生成します。
          </p>
          <p className="text-xs text-amber-300/80 mt-1">
            パディング/速度のみ変えた場合は「パディングのみ反映 (無料)」、
            テキスト・感情・声色を変えた場合は「全シーン一括再生成」。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">
            コスト:{" "}
            <span className="text-emerald-300 font-mono">
              {formatUsd(totalCost.usd, 4)}
            </span>
            <span className="text-slate-500 ml-1">
              ({formatJpy(totalCost.jpy)} / {totalCost.credits} credits)
            </span>
          </span>
          <button
            className="btn-ghost"
            disabled={running}
            onClick={onApplyPaddingOnly}
            title="既存の tts_full.mp3 を使って per-line audio を再構築。API再呼び出しなし"
          >
            パディングのみ反映 (無料)
          </button>
          {!confirming ? (
            <button
              className="btn-secondary"
              disabled={running}
              onClick={() => setConfirming(true)}
            >
              全シーン一括再生成
            </button>
          ) : (
            <>
              <button
                className="btn-ghost"
                onClick={() => setConfirming(false)}
              >
                キャンセル
              </button>
              <button
                className="btn-danger"
                disabled={running}
                onClick={onForceRegen}
              >
                本当に {formatUsd(totalCost.usd, 4)} 使う
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// TTS送信原文プレビュー (ElevenLabsへの実送信文字列を可視化)
// ─────────────────────────────────────────────────────────

function TtsSourcePreview() {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const sp = ctx.detail.screenplay;
  const [data, setData] = useState<{
    text: string;
    char_count: number;
    separator: string;
    line_specs: {
      scene_idx: number;
      line_idx: number;
      char_start: number;
      char_end: number;
    }[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(true);

  // screenplay 内容が変わったら refetch (slider/text編集後の即時反映)
  const screenplayKey = useMemo(() => {
    const lines: string[] = [];
    sp.scenes.forEach((s) =>
      (s.lines ?? []).forEach((l) => lines.push(l.text)),
    );
    return lines.join("|");
  }, [sp]);

  useEffect(() => {
    let cancel = false;
    setError(null);
    api
      .ttsSource(ts)
      .then((d) => {
        if (!cancel) setData(d);
      })
      .catch((e) => {
        if (!cancel) setError(String(e));
      });
    return () => {
      cancel = true;
    };
  }, [ts, screenplayKey]);

  if (error) {
    return (
      <div className="card border-rose-700/40 bg-rose-900/10 mt-4 text-xs text-rose-200">
        TTS送信原文の取得失敗: {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card border-sky-700/40 bg-sky-900/10 mt-4 text-xs text-slate-400">
        TTS送信原文を取得中...
      </div>
    );
  }

  // 各 line を別色で、separator は "·" で可視化したセグメントに分解
  type Seg = {
    kind: "line" | "sep";
    text: string;
    idx?: number;
    key: string;
  };
  const segs: Seg[] = [];
  let cursor = 0;
  data.line_specs.forEach((spec, i) => {
    if (spec.char_start > cursor) {
      segs.push({
        kind: "sep",
        text: data.text.slice(cursor, spec.char_start),
        key: `sep-${cursor}-${spec.char_start}`,
      });
    }
    segs.push({
      kind: "line",
      text: data.text.slice(spec.char_start, spec.char_end),
      idx: i,
      key: `line-${i}`,
    });
    cursor = spec.char_end;
  });
  if (cursor < data.text.length) {
    segs.push({
      kind: "sep",
      text: data.text.slice(cursor),
      key: `sep-tail-${cursor}`,
    });
  }

  // separator を点滅文字で見える化
  const renderSep = (s: string) =>
    s.replace(/ /g, "·").replace(/\t/g, "→").replace(/\n/g, "↵\n");

  return (
    <div className="card border-sky-700/40 bg-sky-900/10 mt-4">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <h3 className="font-semibold text-sky-200">
            TTS送信原文 (ElevenLabs に実送信される文字列)
          </h3>
          <p className="text-[11px] text-slate-400 mt-0.5">
            <span className="font-mono">{data.char_count}</span> 文字 ·{" "}
            <span className="font-mono">{data.line_specs.length}</span> line ·
            区切り{" "}
            <span className="font-mono bg-slate-800 px-1 rounded">
              "{renderSep(data.separator)}"
            </span>
          </p>
        </div>
        <button
          className="btn-ghost text-xs"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "折りたたむ" : "展開"}
        </button>
      </div>
      {open && (
        <div className="mt-1 p-3 rounded bg-slate-950/70 border border-slate-800 font-mono text-[13px] leading-7 break-all whitespace-pre-wrap">
          {segs.map((s) =>
            s.kind === "line" ? (
              <span
                key={s.key}
                className={
                  ((s.idx ?? 0) % 2 === 0
                    ? "bg-emerald-900/30 text-emerald-100"
                    : "bg-sky-900/30 text-sky-100") + " px-0.5 rounded-sm"
                }
                title={`line #${s.idx} (${s.text.length}字)`}
              >
                {s.text}
              </span>
            ) : (
              <span key={s.key} className="text-slate-500" title="separator">
                {renderSep(s.text)}
              </span>
            ),
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// 全シーンTTSをマージしたプレビュー
// ─────────────────────────────────────────────────────────

function MergedTTSPlayer() {
  const ctx = useShellCtx();
  const v = ctx.detail.progress.stages.tts.regen_count;
  return (
    <div className="card border-emerald-700/40 bg-slate-800/60 mt-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="font-semibold">全シーンTTS (one-shot)</h3>
          <p className="text-xs text-slate-400 mt-1">
            screenplay全体を1 API call
            で生成した結果。シーン間が連続したプロソディで再生されます。
          </p>
        </div>
        <span className="text-xs text-slate-500">バージョン: regen×{v}</span>
      </div>
      <audio
        key={`merged-tts-${v}`}
        src={ttsMergedAssetUrl(ctx.detail.timestamp, v)}
        controls
        preload="metadata"
        className="w-full mt-3 h-10"
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// シーンカード
// ─────────────────────────────────────────────────────────

function SceneTTSCard({
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

// ─────────────────────────────────────────────────────────
// 1ライン (試聴 + テキスト編集のみ)
// ─────────────────────────────────────────────────────────

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
