// StageTTS.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// ElevenLabs のグローバル設定を編集する 3 control:
//   - SpeedControl   : 全体の発話速度 (0.5x-2.0x)
//   - SilenceControl : 無音圧縮の on/off + 最大 ms
//   - ModelSelector  : モデル切替 (eleven_v3 / eleven_multilingual_v2 / ...)
//
// 3 つとも `api.set*` + `ctx.reloadConfig()` で server state を更新するため
// `useShellCtx` に依存する。Stage 2 (TTS) ページの PricingBanner 内部から
// 呼ばれる。

import { useState } from "react";

import { api } from "../../api";
import type { TtsPricing } from "../../types";
import { useShellCtx } from "../StageGate";

export function SpeedControl({ pricing }: { pricing: TtsPricing }) {
  const ctx = useShellCtx();
  const [draft, setDraft] = useState(pricing.global_speed);
  const [saving, setSaving] = useState(false);

  const native = Math.max(0.7, Math.min(1.2, draft));
  const atempo = draft / native;

  const commit = async (next: number) => {
    if (Math.abs(next - pricing.global_speed) < 0.001) return;
    setSaving(true);
    try {
      await api.setSpeed(next);
      await ctx.reloadConfig();
    } catch (e) {
      alert(`速度変更失敗: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const onCommit = () => {
    void commit(draft);
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
                void commit(v);
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

export function SilenceControl({ pricing }: { pricing: TtsPricing }) {
  const ctx = useShellCtx();
  const [enabled, setEnabled] = useState(pricing.trim_silences);
  const [draftMs, setDraftMs] = useState(pricing.max_silence_ms);
  const [saving, setSaving] = useState(false);

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

export function ModelSelector({ pricing }: { pricing: TtsPricing }) {
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
