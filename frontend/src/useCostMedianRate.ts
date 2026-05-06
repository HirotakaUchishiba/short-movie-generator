import { useEffect, useState } from "react";
import { api } from "./api";
import type { CostMedianRate, CostStage } from "./types";

export interface CostMedianRateState {
  rate: CostMedianRate | null;
  loading: boolean;
  error: string | null;
}

// 履歴ベースの per-unit cost (= median) を取得する hook。
// model 未指定なら fetch しない (= insufficient と同等)。
export function useCostMedianRate(
  stage: CostStage,
  model: string | undefined,
): CostMedianRateState {
  const [rate, setRate] = useState<CostMedianRate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!model) {
      setRate(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.cost
      .medianRate(stage, model)
      .then((r) => {
        if (!cancelled) setRate(r);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [stage, model]);

  return { rate, loading, error };
}

// rate × units で見積もり。履歴不足なら null を返す (= UI で「—」表示)。
export function applyRate(
  rate: CostMedianRate | null,
  units: number,
): { usd: number; jpy: number } | null {
  if (!rate || rate.usd_per_unit == null) return null;
  const usd = rate.usd_per_unit * units;
  return { usd, jpy: usd * rate.jpy_per_usd };
}
