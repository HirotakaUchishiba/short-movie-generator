// api.ts から抽出 (= §3.1.3 helper 分離)。
//
// Cost Tracking 関連 endpoint (= /api/cost/*) の client。実コスト履歴ベースの
// 動的見積もり + レポートを返す。stage-cache と同じく http を inject で受け
// 取る pure factory にして循環依存を避ける。

import type {
  CostEstimate,
  CostMedianRate,
  CostOverallReport,
  CostPricebookResponse,
  CostProjectReport,
  CostStage,
} from "../types";

type HttpFn = <T>(path: string, init?: RequestInit) => Promise<T>;

export interface CostApi {
  pricebook: () => Promise<CostPricebookResponse>;
  medianRate: (stage: CostStage, model: string) => Promise<CostMedianRate>;
  estimate: (
    stage: CostStage,
    params: Record<string, string | number>,
  ) => Promise<CostEstimate>;
  projectReport: (ts: string) => Promise<CostProjectReport>;
  overallReport: (since?: string) => Promise<CostOverallReport>;
}

export function makeCostApi(http: HttpFn): CostApi {
  return {
    pricebook: () => http<CostPricebookResponse>("/api/cost/pricebook"),
    medianRate: (stage, model) =>
      http<CostMedianRate>(
        `/api/cost/median/${stage}?model=${encodeURIComponent(model)}`,
      ),
    estimate: (stage, params) => {
      const q = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => q.set(k, String(v)));
      return http<CostEstimate>(`/api/cost/estimate/${stage}?${q.toString()}`);
    },
    projectReport: (ts) =>
      http<CostProjectReport>(`/api/cost/report/project/${ts}`),
    overallReport: (since) => {
      const q = since ? `?since=${encodeURIComponent(since)}` : "";
      return http<CostOverallReport>(`/api/cost/report${q}`);
    },
  };
}
