// StageTTS.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 全シーン TTS を一括再生成するアクションバー。「パディングのみ反映 (= 無料)」と
// 「全シーン一括再生成 (= API 課金)」の 2 操作を提供する。後者は誤クリック防止の
// 2 段階確認 (confirming state) を持つ。

import { useState } from "react";

import { type CostBreakdown, formatJpy, formatUsd } from "../../tts-cost";
import { useShellCtx } from "../StageGate";

export function BulkRegenBar({ totalCost }: { totalCost: CostBreakdown }) {
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
