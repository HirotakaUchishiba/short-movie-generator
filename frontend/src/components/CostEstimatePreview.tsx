import { useEffect, useState } from "react";
import { api } from "../api";
import type { CostEstimate, CostStage } from "../types";

interface Props {
  stage: CostStage;
  /** stage に応じた param (= /api/cost/estimate のクエリ)。
   * 例: kling なら { duration_sec: 5.0, model: "kling-v3-standard" } */
  params: Record<string, string | number>;
  /** params が空 / disabled なら fetch しない (= UI 上は何も出さない) */
  disabled?: boolean;
}

const CONFIDENCE_LABEL: Record<CostEstimate["confidence"], string> = {
  history: "履歴 median",
  partial: "履歴一部",
  insufficient: "履歴不足",
};

const CONFIDENCE_COLOR: Record<CostEstimate["confidence"], string> = {
  history: "text-emerald-300",
  partial: "text-amber-300",
  insufficient: "text-rose-300",
};

export function CostEstimatePreview({ stage, params, disabled }: Props) {
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (disabled) {
      setEstimate(null);
      return;
    }
    let cancelled = false;
    api.cost
      .estimate(stage, params)
      .then((e) => {
        if (!cancelled) setEstimate(e);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [stage, JSON.stringify(params), disabled]);

  if (disabled) return null;
  if (error) {
    return (
      <span className="text-xs text-slate-500">
        見積取得失敗: {error.slice(0, 80)}
      </span>
    );
  }
  if (!estimate) {
    return <span className="text-xs text-slate-500">見積取得中…</span>;
  }
  const usd = estimate.cost_usd;
  const usdLabel = usd != null ? `$${usd.toFixed(3)}` : "見積不可";
  return (
    <span className={`text-xs ${CONFIDENCE_COLOR[estimate.confidence]}`}>
      推定 {usdLabel}
      <span className="ml-1 text-slate-400">
        ({CONFIDENCE_LABEL[estimate.confidence]} · n={estimate.sample_size})
      </span>
    </span>
  );
}
