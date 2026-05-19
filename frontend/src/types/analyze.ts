// types.ts から抽出 (= §3.1.3 type 分離)。
//
// analyze pipeline (= 参考動画から台本 JSON を生成) 関連型。
// job lifecycle / phase 構成 / cost dry-run 結果 / reference video upload を
// SSE / REST 両 path で扱う。

export interface AnalyzeOptions {
  fps?: number;
}

export interface ReferenceVideo {
  sha256: string;
  original_name: string;
  size_bytes: number;
  duration_sec: number | null;
  uploaded_at: string;
  last_used_at: string | null;
}

export interface ReferenceVideoUploadResult extends ReferenceVideo {
  deduplicated: boolean;
}

export type AnalyzeStatus =
  | "pending"
  | "dryrunning"
  | "awaiting_confirm"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type AnalyzePhase =
  | "frames"
  | "audio"
  | "whisper"
  | "acoustic"
  | "claude"
  | "save";

export interface AnalyzePhaseRecord {
  phase: AnalyzePhase;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  cost_usd: number | null;
  error: string | null;
}

export interface AnalyzeJob {
  id: string;
  video_sha256: string;
  options: AnalyzeOptions;
  status: AnalyzeStatus;
  current_phase: AnalyzePhase | null;
  error: string | null;
  estimated_cost_usd: number | null;
  actual_cost_usd: number | null;
  screenplay_path: string | null;
  style_name: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cancellation_requested: boolean;
}

export interface AnalyzeJobDetail extends AnalyzeJob {
  phases: AnalyzePhaseRecord[];
}

export interface DryrunCompleteEvent {
  frame_count: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  cost_jpy: number | null;
  confidence: "history" | "insufficient" | "partial";
  sample_size: number;
  token_breakdown?: Record<string, number>;
  breakdown?: Record<string, unknown>;
}
