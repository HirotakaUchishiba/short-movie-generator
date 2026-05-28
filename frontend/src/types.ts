// Scene 内で Identity / Annotation を参照するため先に import (完全 screenplay と
// 抽象台本の両者で同じ型を共有する)。barrel re-export は末尾でも実行する。
import type { Annotation, Identity } from "./types/abstract-screenplay";

export type StageName =
  | "script"
  | "tts"
  | "bg"
  | "kling"
  | "scene"
  | "overlay"
  | "final_import"
  | "publish";

// QA failure tag は backend (qa/categories.py) を SSOT とし、
// /api/config/qa-tags 経由で取得する。型は string に緩めて runtime validate に
// 任せる (= 列挙の追加を frontend と同期する手間をなくす)。
export type QaFailureTag = string;

export interface QaFailureTagDef {
  tag: string;
  label: string;
  axis: string;
}

export interface QaTagsConfig {
  tags: QaFailureTagDef[];
  axis_labels: Record<string, string>;
}

export interface RejectBody {
  stage: StageName;
  scene_idx?: number | null;
  line_idx?: number | null;
  tags: string[];
  note?: string;
}

export interface RejectResponse {
  ok: true;
  failure_id: number;
  archive_dir: string;
}

// Stage 8 / 9 用の型
export interface FinalVersion {
  filename: string;
  imported_at: string;
  duration_sec: number | null;
  size_bytes: number;
  audio_match_score: number | null;
  source: "watch" | "ui" | "cli";
  is_canonical: boolean;
}

export interface PublishedPost {
  platform: "youtube" | "instagram" | "tiktok";
  video_id: string | null;
  url: string | null;
  manual: boolean;
  published_at: string;
}

// 各 stage / phase の失敗時に backend が tmp-progress.json に書く構造化
// error envelope。詳細は docs/plannings/2026-05-11_pipeline-failure-detail-ui.md
// 全 field optional (= 後方互換: error_detail 自体が無い旧 project は failed 表示しない)
export interface StageErrorDetail {
  type:
    | "credit_exhausted"
    | "rate_limit"
    | "auth_failure"
    | "quota_exceeded"
    | "context_too_long"
    | "safety_filter"
    | "network_timeout"
    | "disk_full"
    | "unknown";
  message: string;
  request_id?: string | null;
  actionable_hint?: string | null;
  retry_cost_estimate_usd?: number | null;
  occurred_at?: string | null;
  // analyze の claude / whisper や publish の youtube / instagram など、
  // 外側 stage より細かい sub-phase 名 (= 任意)
  failed_phase?: string | null;
}

export interface StageStatus {
  generated_at: string | null;
  approved_at: string | null;
  regen_count: number;
  // failed 時に backend が立てる (= analyze は既存、Stage 1-8 は新規)
  status?: "running" | "completed" | "failed" | null;
  // failed 時の構造化原因。UI は StageFailureAlert でこれを表示する
  error_detail?: StageErrorDetail | null;
  // 後方互換: raw message :500 截断 (= analyze の旧 schema)
  error?: string | null;
}

export interface Progress {
  // backend の STAGES は ["analyze", ...StageName] で analyze (= Stage 0) も
  // 含む。analyze block は他と同じ shape (= StageStatus) を持つが、StageName
  // から外している (= analyze は from-reference-video 経路だけが立てる special)
  // ため optional として併記する。
  stages: { analyze?: StageStatus } & Record<StageName, StageStatus>;
}

export interface Acoustic {
  pitch_trend?: string;
  rms_peak?: number;
  wpm?: number;
}

export interface VoiceOverrides {
  voice_id?: string;
  stability?: number;
  style?: number;
  similarity_boost?: number;
  rate_pct?: number;
}

export interface SubtitleChunk {
  text: string;
  start?: number;
  end?: number;
  // クライアント側で付与される React key 用 ID。API 送信時に strip される。
  _uid?: string;
}

export interface Line {
  text: string;
  tts_text?: string;
  start: number;
  end?: number;
  rate?: string;
  emotion?: string;
  emotion_intensity?: "soft" | "normal" | "strong";
  audio_tags?: string[];
  delivery?: string;
  acoustic?: Acoustic;
  voice_overrides?: VoiceOverrides;
  pronunciation_hints?: Record<string, string>;
  speaker?: string;
  subtitles?: SubtitleChunk[];
  hidden?: boolean;
  // クライアント側で付与される React key 用 ID。API 送信時に strip される。
  _uid?: string;
}

export interface CharacterDef {
  name?: string;
  ref?: string;
}

export interface Scene {
  duration: number;
  background_prompt?: string;
  animation_prompt?: string;
  animation_style?: "subtle" | "standard" | "expressive";
  characters?: CharacterDef[];
  lipsync?: boolean;
  lines?: Line[];
  identity?: Identity;
  annotation?: Annotation;
  // クライアント側で付与される React key 用 ID。API 送信時に strip される。
  _uid?: string;
}

export interface Screenplay {
  caption?: string;
  subtitle_y_from_bottom?: number;
  scenes: Scene[];
}

// Stage 0 (analyze) の進行状態。null は legacy template 経路 project
// (= analyze pipeline を経由しない) を意味する。
export type AnalyzeStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | null;

export interface ProjectListItem {
  timestamp: string;
  screenplay_name: string | null;
  display_title: string;
  caption_hashtags: string;
  scene_count: number;
  has_bg_thumbnail: boolean;
  created_at: string;
  current_stage: StageName | null;
  progress: Progress;
  analyze_status?: AnalyzeStageStatus;
  analyze_job_id?: string | null;
}

export interface ProjectDetail {
  timestamp: string;
  screenplay_name: string | null;
  screenplay: Screenplay | null;
  progress: Progress;
  current_stage: StageName | null;
  analyze_job_id: string | null;
  analyze_status?: AnalyzeStageStatus;
}

export interface VoiceLibraryEntry {
  voice_id: string;
  name?: string;
  gender?: string;
  age?: string;
  language?: string;
}

export interface AvailableModel {
  id: string;
  credit_multiplier: number;
  supports_context: boolean;
}

export interface TtsPricing {
  model: string;
  credit_multiplier: number;
  usd_per_credit: number;
  available_models: AvailableModel[];
  global_speed: number;
  speed_min: number;
  speed_max: number;
  trim_silences: boolean;
  max_silence_ms: number;
  note?: string;
}

export interface ServerConfig {
  stages: StageName[];
  emotions: string[];
  available_audio_tags: string[];
  emotion_audio_tags: Record<string, string[]>;
  voice_library: VoiceLibraryEntry[];
  default_voice_id: string;
  default_stability: number;
  default_similarity_boost: number;
  default_style: number;
  video_width: number;
  video_height: number;
  subtitle_y_from_bottom: number;
  tts_pricing: TtsPricing;
  cost_models: {
    tts: string;
    bg: string;
    kling: string;
    lipsync: string;
    analyze: string;
  };
}

export interface JobStatus {
  id: string;
  kind: string;
  ts: string;
  status: "running" | "completed" | "failed";
  elapsed: number;
  error: string | null;
}

// ─── Analyze pipeline / Location / CharacterMeta ─────────
// 関連型は ./types/analyze.ts / ./types/locations.ts に移管済 (= §3.1.3)。
export * from "./types/analyze";
export * from "./types/locations";

// ─── 抽象台本 (Stage 1「素材」セクション編集用) ─────────
// 関連型は ./types/abstract-screenplay.ts に移管済 (= §3.1.3)。
export * from "./types/abstract-screenplay";

// ─── Stage 3 (BG) / Stage 4 (Kling) cache decision flow ─────────
// 関連型は ./types/cache.ts に移管済 (= §3.1.3)。barrel re-export。
export * from "./types/cache";

// ─────────────────── Cost Tracking ───────────────────
// Cost 関連の型は ./types/cost.ts に移管済 (= §3.1.3)。既存 import path
// (= `from "../types"`) を破壊しないよう barrel re-export を維持する。
export * from "./types/cost";
