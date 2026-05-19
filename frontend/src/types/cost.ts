// types.ts から抽出 (= §3.1.3 type 分離)。
//
// Cost tracking API (= /api/cost/*) の Response 型群。
// stage 別の median rate / estimate / report / pricebook lookup を表現する。

export type CostStage = "tts" | "bg" | "kling" | "lipsync" | "analyze";

export interface CostMedianRate {
  stage: string;
  model: string;
  usd_per_unit: number | null;
  unit_label: string;
  confidence: "history" | "insufficient";
  sample_size: number;
  jpy_per_usd: number;
}

export interface CostEstimate {
  cost_usd: number | null;
  cost_jpy: number | null;
  confidence: "history" | "insufficient" | "partial";
  sample_size: number;
  breakdown: Record<string, unknown>;
  note: string;
}

export interface CostProjectReport {
  project_ts: string;
  record_count: number;
  total_usd: number;
  total_jpy: number;
  per_stage: Record<string, number>;
  per_provider: Record<string, number>;
  per_scene: Record<string, number>;
  generated_at: string;
}

export interface CostOverallReport {
  project_count: number;
  record_count: number;
  total_usd: number;
  total_jpy: number;
  per_project: Record<string, number>;
  per_stage: Record<string, number>;
  per_provider: Record<string, number>;
  generated_at: string;
}

export interface CostPricebookResponse {
  pricebook: {
    version: number;
    updated_at?: string;
    jpy_per_usd: number;
    providers: Record<string, Record<string, Record<string, unknown>>>;
  };
  jpy_per_usd: number;
}
