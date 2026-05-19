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

// ─── Analyze pipeline (参考動画から台本JSON生成) ─────────

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

// ─── Location / CharacterMeta ─────────

export type CameraDistance = "close-up" | "medium-close" | "medium" | "wide";

// グローバルなロケ集 (locations/<id>.json)。
export interface Location {
  id: string;
  decor: string;
  lighting: string;
  color_palette: string;
  props: string;
  camera_distance: CameraDistance;
}

// グローバルなキャラ voice メタ (characters/<id>.json)。<id> は衣装込みの
// 焼き込みキャラ ID。
export interface CharacterMeta {
  id: string;
  voice_overrides?: Record<string, unknown>;
}

// ─── 抽象台本 (Stage 1「素材」セクション編集用) ─────────
// 完全 screenplay とは別物。caption + scenes[].lines[] + シーンごとの設定。
// compose で完全 screenplay に展開される。
export interface AbstractLine {
  text: string;
  start: number;
  end?: number;
  emotion?: string;
  delivery?: string;
  speaker?: string;
  rate?: string;
  pronunciation_hints?: Record<string, string>;
  // クライアント側で付与される React key 用 ID。API 送信時に strip される。
  _uid?: string;
}

// Layer 1 (clip library) hard match キー。4 フィールドすべて揃えば
// scene["identity"] として書き出され、cache lookup で hit すると AI 課金を回避。
// 1 つでも欠けると compose で identity が undefined になり cold path (AI 生成) が走る。
export interface Identity {
  character_refs: string[];
  location_ref: string;
  start_emotion: string;
  camera_distance: CameraDistance;
}

// Layer 1 soft rank に使う注釈。完全一致が無くても compatible_with 経由で fallback。
// 全 field optional (= 1 field でも書かれていれば送信)。
export interface Annotation {
  visual_intent_id?: string;
  duration_bucket?: 5 | 10;
  motion_intensity?: "low" | "medium" | "high";
  generation_seed?: number;
}

export interface AbstractScene {
  lines: AbstractLine[];
  duration?: number;
  // シーン別の人物指定 (= featured_characters の subset)
  //   未定義 = featured_characters 全員 (= 主に単一キャラ動画用のショートカット)
  //   []     = 0 人 (背景のみ)
  //   [...]  = 指定された ID のキャラだけ
  character_selection?: string[];
  camera_distance?: CameraDistance;
  location_ref?: string;
  animation_style?: "subtle" | "standard" | "expressive";
  // Layer 1 (clip library) identity + annotation
  identity?: Identity;
  annotation?: Annotation;
  // クライアント側で付与される React key 用 ID。API 送信時に strip される。
  _uid?: string;
}

export interface AbstractScreenplay {
  caption: string;
  scenes: AbstractScene[];
  // この動画に登場させる人物の characters/<id>.png キーのリスト。
  // シーンの登場人物・話者の候補として使われる。
  // 2026-05-17 schema 撤廃: speaker_to_ref / speaker_profiles は廃止。
  // analyze が line.speaker に resolved id を直書きするようになった。
  featured_characters?: string[];
  // future-proof で broadly に許容する。
  [k: string]: unknown;
}

export interface AbstractDiagnostics {
  // 2026-05-17 schema 撤廃: 旧 raw `speaker_N` 形式の残骸検出に使われる
  // (= migration 漏れの警告用)
  unmapped_speakers: string[];
  scenes_without_characters: number[];
  // location_ref が空のシーン idx (= analyze pre-fill 後、ユーザが意図的に
  // 空に戻したケースを CompletenessBanner で警告するため)
  scenes_without_location: number[];
  // camera_distance が enum 外のシーン (= 通常 analyze 経由では発生しないが
  // 旧データ / 手動編集の漏れを検知するため)
  invalid_camera_distance: { scene_idx: number; value: string }[];
  unknown_character_refs: {
    featured: string[];
    character_selection: { scene_idx: number; ref: string }[];
    speaker: { scene_idx: number; line_idx: number; ref: string }[];
  };
}

export interface AbstractScreenplayResponse {
  screenplay_path: string;
  abstract: AbstractScreenplay;
}

// ─── Stage 3 (BG) / Stage 4 (Kling) cache decision flow ─────────
// 関連型は ./types/cache.ts に移管済 (= §3.1.3)。barrel re-export。
export * from "./types/cache";

// ─────────────────── Cost Tracking ───────────────────
// Cost 関連の型は ./types/cost.ts に移管済 (= §3.1.3)。既存 import path
// (= `from "../types"`) を破壊しないよう barrel re-export を維持する。
export * from "./types/cost";
