// StageKling.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 全シーン Kling 動画を一括再生成するアクションバー (= 高額ステージなので
// 2 段階確認)。`decisionsBulk(ts, "all-fresh")` で cache 採用も含めた決定を
// 破棄し、全シーンを fresh queue 化してから再生成 job を起動する。

import { useState } from "react";

import { api } from "../../api";
import { useShellCtx } from "../StageGate";
import { formatKlingCost } from "./kling-utils";

export function BulkKlingRegenBar({ totalCost }: { totalCost: number | null }) {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const [confirming, setConfirming] = useState(false);
  const running = ctx.jobStatus?.status === "running";

  const onResetToScan = async () => {
    setConfirming(false);
    try {
      await api.klingCache.decisionsBulk(ts, "all-fresh");
      await ctx.regen({ stage: "kling" });
    } catch (e) {
      console.error("[StageKling] kling cache all-fresh decisions failed:", e);
    }
  };

  return (
    <div className="card border-rose-700/40 bg-rose-900/10 mb-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">全シーン Kling動画を一括再生成</h3>
          <p className="text-xs text-slate-400 mt-1">
            cache 採用も新規生成も含め、全シーンを破棄して新規生成します。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">
            合計コスト:{" "}
            <span className="text-rose-300 font-mono">
              {formatKlingCost(totalCost)}
            </span>
          </span>
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
                onClick={onResetToScan}
              >
                本当に {formatKlingCost(totalCost)} 使う
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
