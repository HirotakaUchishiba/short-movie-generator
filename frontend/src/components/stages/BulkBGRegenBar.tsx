// StageBG.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 全シーン背景を一括再生成するアクションバー (= 2 段階確認)。
// `decisionsBulk(ts, "all-fresh")` で cache 採用を含めた決定を破棄し、
// 全シーンを fresh queue 化してから Stage 3 を再生成する。

import { useState } from "react";

import { api } from "../../api";
import { useShellCtx } from "../StageGate";
import { formatBgCost } from "./bg-utils";

export function BulkBGRegenBar({
  totalCost,
  sceneCount,
}: {
  totalCost: number | null;
  sceneCount: number;
}) {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const [confirming, setConfirming] = useState(false);
  const running = ctx.jobStatus?.status === "running";

  const onResetToScan = async () => {
    setConfirming(false);
    // 全シーンを fresh queue にして Stage 3 を再生成 → 結果は再 scan ベース。
    try {
      await api.bgCache.decisionsBulk(ts, "all-fresh");
      await ctx.regen({ stage: "bg" });
    } catch (e) {
      console.error("[StageBG] bg cache all-fresh decisions failed:", e);
    }
  };

  return (
    <div className="card border-amber-700/40 bg-amber-900/10 mb-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">全シーン背景を一括再生成</h3>
          <p className="text-xs text-slate-400 mt-1">
            cache 採用も新規生成も含め、全シーンを破棄して新規生成します。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">
            {sceneCount}枚 ・合計コスト{" "}
            <span className="text-amber-300 font-mono">
              {formatBgCost(totalCost)}
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
                本当に {formatBgCost(totalCost)} 使う
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
