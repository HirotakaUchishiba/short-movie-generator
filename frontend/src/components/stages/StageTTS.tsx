import { useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import StageGate, { useShellCtx } from "../StageGate";
import { ttsAssetUrl, ttsMergedAssetUrl, api } from "../../api";
import type { Line, Scene, TtsPricing } from "../../types";

export default function StageTTS() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const totalCost = useMemo(
    () => estimateScreenplayCost(sp.scenes, ctx.serverConfig.tts_pricing),
    [sp.scenes, ctx.serverConfig.tts_pricing],
  );

  return (
    <StageGate
      stage="tts"
      title="Stage 2: TTS音声 (one-shot方式)"
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
          <SceneTTSCard key={sIdx} scene={scene} sIdx={sIdx} />
        ))}
      </div>
    </StageGate>
  );
}

// ─────────────────────────────────────────────────────────
// コスト計算
// ─────────────────────────────────────────────────────────

function countChars(line: Line): number {
  return (line.text ?? "").length;
}

function estimateLineCost(line: Line, pricing: TtsPricing) {
  const chars = countChars(line);
  const credits = chars * pricing.credit_multiplier;
  const usd = credits * pricing.usd_per_credit;
  return { chars, credits, usd, jpy: usd * 150 };
}

function estimateSceneCost(scene: Scene, pricing: TtsPricing) {
  const lines = scene.lines ?? [];
  return lines.reduce(
    (acc, l) => {
      const c = estimateLineCost(l, pricing);
      return {
        chars: acc.chars + c.chars,
        credits: acc.credits + c.credits,
        usd: acc.usd + c.usd,
        jpy: acc.jpy + c.jpy,
      };
    },
    { chars: 0, credits: 0, usd: 0, jpy: 0 },
  );
}

function estimateScreenplayCost(scenes: Scene[], pricing: TtsPricing) {
  return scenes.reduce(
    (acc, s) => {
      const c = estimateSceneCost(s, pricing);
      return {
        chars: acc.chars + c.chars,
        credits: acc.credits + c.credits,
        usd: acc.usd + c.usd,
        jpy: acc.jpy + c.jpy,
      };
    },
    { chars: 0, credits: 0, usd: 0, jpy: 0 },
  );
}

// ─────────────────────────────────────────────────────────
// 価格バナー
// ─────────────────────────────────────────────────────────

function PricingBanner({
  pricing,
  totalCost,
}: {
  pricing: TtsPricing;
  totalCost: { chars: number; credits: number; usd: number; jpy: number };
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
          <Stat
            label="全シーン1回生成"
            value={`$${totalCost.usd.toFixed(3)}`}
          />
          <Stat label="(円換算)" value={`¥${totalCost.jpy.toFixed(1)}`} />
        </div>
      </div>
      <SpeedControl pricing={pricing} />
      <SilenceControl pricing={pricing} />
    </div>
  );
}

function SpeedControl({ pricing }: { pricing: TtsPricing }) {
  const ctx = useShellCtx();
  const [draft, setDraft] = useState(pricing.global_speed);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(pricing.global_speed);
  }, [pricing.global_speed]);

  const native = Math.max(0.7, Math.min(1.2, draft));
  const atempo = draft / native;

  const onCommit = async () => {
    if (Math.abs(draft - pricing.global_speed) < 0.001) return;
    setSaving(true);
    try {
      await api.setSpeed(draft);
      await ctx.reloadConfig();
    } catch (e) {
      alert(`速度変更失敗: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-3 pt-3 border-t border-slate-700/40">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs text-slate-400">全体の発話速度</div>
        <div className="flex items-center gap-3 text-xs">
          <span className="text-slate-300 font-mono">{draft.toFixed(2)}x</span>
          <span className="text-slate-500">
            (native={native.toFixed(2)} × atempo={atempo.toFixed(2)})
          </span>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-slate-500 w-8">0.5x</span>
        <input
          type="range"
          min={pricing.speed_min}
          max={pricing.speed_max}
          step={0.05}
          value={draft}
          onChange={(e) => setDraft(Number(e.target.value))}
          onMouseUp={onCommit}
          onTouchEnd={onCommit}
          disabled={saving}
          className="flex-1 accent-emerald-500"
        />
        <span className="text-[10px] text-slate-500 w-8 text-right">2.0x</span>
        <div className="flex gap-1">
          {[0.75, 1.0, 1.25, 1.5, 1.75, 2.0].map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => {
                setDraft(v);
                setTimeout(onCommit, 0);
              }}
              className={
                Math.abs(draft - v) < 0.025
                  ? "px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-600 text-white"
                  : "px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-700 text-slate-300 hover:bg-slate-600"
              }
            >
              {v}x
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function SilenceControl({ pricing }: { pricing: TtsPricing }) {
  const ctx = useShellCtx();
  const [enabled, setEnabled] = useState(pricing.trim_silences);
  const [draftMs, setDraftMs] = useState(pricing.max_silence_ms);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setEnabled(pricing.trim_silences);
    setDraftMs(pricing.max_silence_ms);
  }, [pricing.trim_silences, pricing.max_silence_ms]);

  const commit = async (next: { enabled?: boolean; max_ms?: number }) => {
    setSaving(true);
    try {
      await api.setSilences(next);
      await ctx.reloadConfig();
    } catch (e) {
      alert(`無音圧縮設定変更失敗: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const onToggle = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.checked;
    setEnabled(v);
    commit({ enabled: v });
  };

  const onMsCommit = () => {
    if (Math.abs(draftMs - pricing.max_silence_ms) < 1) return;
    commit({ max_ms: draftMs });
  };

  return (
    <div className="mt-3 pt-3 border-t border-slate-700/40">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs text-slate-400">
          無音圧縮 (long silenceの切詰め)
          <span className="ml-2 text-[10px] text-slate-500">
            指定 ms 以下の無音は残し、超過分はカット
          </span>
        </div>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={enabled}
            onChange={onToggle}
            disabled={saving}
            className="accent-emerald-500"
          />
          <span className={enabled ? "text-emerald-300" : "text-slate-500"}>
            {enabled ? "ON" : "OFF"}
          </span>
        </label>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-slate-500 w-12">50ms</span>
        <input
          type="range"
          min={50}
          max={1000}
          step={25}
          value={draftMs}
          onChange={(e) => setDraftMs(Number(e.target.value))}
          onMouseUp={onMsCommit}
          onTouchEnd={onMsCommit}
          disabled={saving || !enabled}
          className="flex-1 accent-emerald-500"
        />
        <span className="text-[10px] text-slate-500 w-14 text-right">
          1000ms
        </span>
        <span className="font-mono text-xs text-slate-300 w-16 text-right">
          {draftMs}ms
        </span>
      </div>
    </div>
  );
}

function ModelSelector({ pricing }: { pricing: TtsPricing }) {
  const ctx = useShellCtx();
  const [saving, setSaving] = useState(false);

  const onChange = async (model: string) => {
    if (model === pricing.model) return;
    setSaving(true);
    try {
      await api.setModel(model);
      await ctx.reloadConfig();
    } catch (e) {
      alert(`モデル切替失敗: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <select
      className="bg-black/40 border border-current/30 rounded px-2 py-1 font-mono text-base font-bold leading-tight focus:outline-none focus:ring-2 focus:ring-current/50 disabled:opacity-60"
      value={pricing.model}
      onChange={(e) => onChange(e.target.value)}
      disabled={saving}
    >
      {pricing.available_models.map((m) => (
        <option key={m.id} value={m.id} className="bg-slate-900 text-slate-100">
          {m.id} (×{m.credit_multiplier}
          {m.supports_context ? " / 文脈✓" : " / 文脈✗"})
        </option>
      ))}
    </select>
  );
}

function modelMeta(model: string): {
  color: string;
  contextLabel: string;
  qualityLabel: string;
} {
  switch (model) {
    case "eleven_v3":
      return {
        color: "border-amber-500 bg-amber-500/15 text-amber-100",
        contextLabel: "文脈✗",
        qualityLabel: "alpha",
      };
    case "eleven_multilingual_v2":
      return {
        color: "border-emerald-500 bg-emerald-500/15 text-emerald-100",
        contextLabel: "文脈✓",
        qualityLabel: "日本語◎",
      };
    case "eleven_turbo_v2_5":
    case "eleven_turbo_v2":
      return {
        color: "border-sky-500 bg-sky-500/15 text-sky-100",
        contextLabel: "文脈✓",
        qualityLabel: "高速・低品質",
      };
    case "eleven_flash_v2_5":
    case "eleven_flash_v2":
      return {
        color: "border-violet-500 bg-violet-500/15 text-violet-100",
        contextLabel: "文脈✓",
        qualityLabel: "爆速・低品質",
      };
    default:
      return {
        color: "border-slate-500 bg-slate-500/15 text-slate-100",
        contextLabel: "文脈?",
        qualityLabel: "?",
      };
  }
}

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

function BulkRegenBar({
  totalCost,
}: {
  totalCost: { chars: number; credits: number; usd: number; jpy: number };
}) {
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
              ${totalCost.usd.toFixed(4)}
            </span>
            <span className="text-slate-500 ml-1">
              (¥{totalCost.jpy.toFixed(2)} / {totalCost.credits} credits)
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
                本当に ${totalCost.usd.toFixed(4)} 使う
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
  type Seg = { kind: "line" | "sep"; text: string; idx?: number };
  const segs: Seg[] = [];
  let cursor = 0;
  data.line_specs.forEach((spec, i) => {
    if (spec.char_start > cursor) {
      segs.push({
        kind: "sep",
        text: data.text.slice(cursor, spec.char_start),
      });
    }
    segs.push({
      kind: "line",
      text: data.text.slice(spec.char_start, spec.char_end),
      idx: i,
    });
    cursor = spec.char_end;
  });
  if (cursor < data.text.length) {
    segs.push({ kind: "sep", text: data.text.slice(cursor) });
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
          {segs.map((s, i) =>
            s.kind === "line" ? (
              <span
                key={i}
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
              <span key={i} className="text-slate-500" title="separator">
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

function SceneTTSCard({ scene, sIdx }: { scene: Scene; sIdx: number }) {
  const ctx = useShellCtx();
  const lines = scene.lines ?? [];
  const cost = estimateSceneCost(scene, ctx.serverConfig.tts_pricing);
  return (
    <div className="card">
      <div className="flex justify-between items-center mb-3">
        <h3 className="font-semibold">
          シーン{sIdx + 1}{" "}
          <span className="text-slate-400 text-sm font-normal">
            {scene.time} {scene.label} ({scene.duration}s · {lines.length}lines)
          </span>
        </h3>
        <span className="text-xs text-slate-400">
          このシーンの文字数 →{" "}
          <span className="text-emerald-300 font-mono">
            ${cost.usd.toFixed(4)}
          </span>
          <span className="text-slate-500 ml-1">
            (¥{cost.jpy.toFixed(2)} / {cost.credits} credits)
          </span>
        </span>
      </div>
      <div className="space-y-3">
        {lines.map((line, lIdx) => (
          <LineTTSRow key={lIdx} line={line} sIdx={sIdx} lIdx={lIdx} />
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
}: {
  line: Line;
  sIdx: number;
  lIdx: number;
}) {
  const ctx = useShellCtx();
  const [editing, setEditing] = useState(false);
  const cost = estimateLineCost(line, ctx.serverConfig.tts_pricing);
  return (
    <div className="rounded border border-slate-700 bg-slate-900/40 p-3">
      <div className="flex justify-between items-start mb-2 gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium break-words">{line.text}</div>
          <div className="text-xs text-slate-400 mt-1">
            start={line.start}s{line.end != null && `, end=${line.end}s`}
            <span className="mx-1">·</span>
            {cost.chars}字 → ${cost.usd.toFixed(5)}
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
      <LineWaveformEditor line={line} sIdx={sIdx} lIdx={lIdx} />
      {editing && <LineTextEditor line={line} sIdx={sIdx} lIdx={lIdx} />}
    </div>
  );
}

// 波形ビジュアライザ + パディング (silence_after_ms) 編集。
// - speech 部分 (緑) と padding 部分 (アンバー overlay) を視覚化
// - 縦線ハンドルをドラッグして padding 境界を直接調整
// - スライダー (0-2000ms) でも調整可能
// - 値の保存のみ。TTS 再生成は「パディングのみ反映」/「全シーン一括再生成」ボタンで反映。
function LineWaveformEditor({
  line,
  sIdx,
  lIdx,
}: {
  line: Line;
  sIdx: number;
  lIdx: number;
}) {
  const ctx = useShellCtx();
  const defaultMs = ctx.serverConfig.tts_pricing.max_silence_ms;
  const stored = line.silence_after_ms;
  const effective = stored ?? defaultMs;
  const [draft, setDraft] = useState(effective);
  const [saving, setSaving] = useState(false);
  const [fileDur, setFileDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const draggingRef = useRef(false);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const regenCount = ctx.detail.progress.stages.tts.regen_count;
  const audioUrl = ttsAssetUrl(ctx.detail.timestamp, sIdx, lIdx, regenCount);

  useEffect(() => {
    setDraft(stored ?? defaultMs);
  }, [stored, defaultMs]);

  useEffect(() => {
    if (!containerRef.current) return;
    const ws = WaveSurfer.create({
      container: containerRef.current,
      url: audioUrl,
      waveColor: "#10b981",
      progressColor: "#34d399",
      cursorColor: "#fde047",
      height: 56,
      normalize: true,
      barWidth: 2,
      barGap: 1,
      barRadius: 1,
    });
    wsRef.current = ws;
    const onReady = () => setFileDur(ws.getDuration());
    ws.on("ready", onReady);
    ws.on("decode", onReady);
    ws.on("play", () => setPlaying(true));
    ws.on("pause", () => setPlaying(false));
    ws.on("finish", () => setPlaying(false));
    return () => {
      ws.destroy();
      wsRef.current = null;
    };
  }, [audioUrl]);

  const currentPadSec = effective / 1000;
  const draftPadSec = draft / 1000;
  const speechDurInFile = Math.max(0, fileDur - currentPadSec);
  const draftBoundarySec = Math.min(
    speechDurInFile + draftPadSec,
    Math.max(speechDurInFile, fileDur),
  );
  const speechRatio = fileDur > 0 ? speechDurInFile / fileDur : 0;
  const draftRatio = fileDur > 0 ? draftBoundarySec / fileDur : 0;
  const dirty = draft !== effective;

  const commit = async (value: number) => {
    if (value === (stored ?? defaultMs)) return;
    setSaving(true);
    try {
      // patchLine 経由で server-side merge — 並行 commit しても他 line を上書きしない
      await api.patchLine(ctx.detail.timestamp, sIdx, lIdx, {
        silence_after_ms: value,
      });
      await ctx.reload();
    } catch (e) {
      alert(`パディング保存失敗: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const onReset = async () => {
    if (stored === undefined) return;
    setSaving(true);
    try {
      // null で field 削除
      await api.patchLine(ctx.detail.timestamp, sIdx, lIdx, {
        silence_after_ms: null,
      });
      await ctx.reload();
    } catch (e) {
      alert(`パディングリセット失敗: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  // 波形上の縦ハンドルをドラッグ → boundary 位置から padding 値を逆算
  const onHandleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!overlayRef.current || fileDur <= 0) return;
    draggingRef.current = true;
    const rect = overlayRef.current.getBoundingClientRect();
    const onMove = (ev: MouseEvent) => {
      if (!draggingRef.current) return;
      const x = Math.max(0, Math.min(rect.width, ev.clientX - rect.left));
      const ratio = x / rect.width;
      const boundarySec = ratio * fileDur;
      const newPadSec = Math.max(0, fileDur - boundarySec);
      const newPadMs = Math.round(Math.min(2000, newPadSec * 1000));
      setDraft(newPadMs);
    };
    const onUp = () => {
      draggingRef.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      commit(draftRef.current);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  return (
    <div className="mt-2 pt-2 border-t border-slate-800/60">
      <div className="flex items-center gap-2 mb-1.5">
        <button
          type="button"
          className="btn-ghost text-xs px-2 py-1"
          onClick={() => wsRef.current?.playPause()}
          disabled={fileDur === 0}
          title={playing ? "停止" : "再生"}
        >
          {playing ? "⏸" : "▶"}
        </button>
        <div
          ref={overlayRef}
          className="relative flex-1 h-14 bg-slate-950/60 rounded overflow-hidden"
        >
          <div ref={containerRef} className="absolute inset-0" />
          {fileDur > 0 && currentPadSec > 0 && (
            <div
              className="absolute top-0 bottom-0 bg-amber-500/15 pointer-events-none border-l border-amber-500/40"
              style={{
                left: `${speechRatio * 100}%`,
                width: `${(1 - speechRatio) * 100}%`,
              }}
            />
          )}
          {fileDur > 0 && dirty && (
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-yellow-300 pointer-events-none z-10"
              style={{ left: `${draftRatio * 100}%` }}
            />
          )}
          {fileDur > 0 && (
            <div
              className="absolute top-0 bottom-0 w-1.5 cursor-ew-resize bg-emerald-300/80 hover:bg-emerald-200 z-20"
              style={{ left: `calc(${speechRatio * 100}% - 3px)` }}
              onMouseDown={onHandleMouseDown}
              title="ドラッグでpadding境界を調整"
            />
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-slate-500">
        <span>
          話声{" "}
          <span className="font-mono text-emerald-300">
            {speechDurInFile.toFixed(2)}s
          </span>
        </span>
        <span>
          現padding{" "}
          <span className="font-mono text-amber-300">
            {currentPadSec.toFixed(2)}s
          </span>
        </span>
        <span>
          ファイル長{" "}
          <span className="font-mono text-slate-300">
            {fileDur.toFixed(2)}s
          </span>
        </span>
        {dirty && (
          <span className="text-yellow-300">
            → 適用後padding{" "}
            <span className="font-mono">{draftPadSec.toFixed(2)}s</span>
          </span>
        )}
      </div>
      <div className="mt-1.5 flex items-center gap-2 text-xs">
        <span className="text-slate-500 w-20 flex-shrink-0">スライダー</span>
        <span className="text-[10px] text-slate-600 w-6">0</span>
        <input
          type="range"
          min={0}
          max={2000}
          step={25}
          value={draft}
          onChange={(e) => setDraft(Number(e.target.value))}
          onMouseUp={() => commit(draft)}
          onTouchEnd={() => commit(draft)}
          onKeyUp={() => commit(draft)}
          disabled={saving}
          className="flex-1 accent-emerald-500"
        />
        <span className="text-[10px] text-slate-600 w-10 text-right">
          2000ms
        </span>
        <span
          className={
            (dirty ? "text-yellow-300" : "text-slate-300") +
            " font-mono w-14 text-right"
          }
        >
          {draft}ms
        </span>
        <span
          className={
            (stored !== undefined ? "text-emerald-300" : "text-slate-500") +
            " text-[10px] w-10 text-center"
          }
          title={
            stored !== undefined
              ? "このセリフ専用の値"
              : `既定 (グローバル ${defaultMs}ms)`
          }
        >
          {stored !== undefined ? "個別" : "既定"}
        </span>
        <button
          className="btn-ghost text-[10px] py-0.5 px-1.5 disabled:opacity-30"
          onClick={onReset}
          disabled={stored === undefined || saving}
          title="既定値に戻す"
        >
          既定に
        </button>
      </div>
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

  useEffect(() => {
    setDraft(line.text);
  }, [line.text]);

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
