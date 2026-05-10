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

export interface StageStatus {
  generated_at: string | null;
  approved_at: string | null;
  regen_count: number;
}

export interface Progress {
  stages: Record<StageName, StageStatus>;
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
  character_refs?: string[];
  characters?: CharacterDef[];
  location_ref?: string;
  camera_distance?: CameraDistance;
  lipsync?: boolean;
  lines?: Line[];
  // クライアント側で付与される React key 用 ID。API 送信時に strip される。
  _uid?: string;
}

export interface Screenplay {
  caption?: string;
  subtitle_y_from_bottom?: number;
  scenes: Scene[];
}

export interface ProjectListItem {
  timestamp: string;
  screenplay_name: string;
  display_title: string;
  caption_hashtags: string;
  scene_count: number;
  has_bg_thumbnail: boolean;
  created_at: string;
  current_stage: StageName | null;
  progress: Progress;
}

export interface ProjectDetail {
  timestamp: string;
  screenplay_name: string;
  screenplay: Screenplay;
  progress: Progress;
  current_stage: StageName | null;
  analyze_job_id: string | null;
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
  instructions?: string | null;
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

// Compositional Architecture: scene_parts のフィールド型 (= renderPlan.ts と整合)。
// 詳細は docs/plannings/2026-05-10_compositional-architecture.md §4
export interface PartReference {
  id: string;
  params?: Record<string, unknown>;
}
export interface StickerPart {
  id: string;
  at: number;
  duration?: number;
  params?: Record<string, unknown>;
}
export interface LowerThirdPart {
  id: string;
  at: number;
  duration: number;
  params?: Record<string, unknown>;
}
export interface SfxPart {
  path: string;
  at: number;
  volume?: number;
}
export interface SceneParts {
  subtitle_style?: PartReference;
  stickers?: StickerPart[];
  lower_third?: LowerThirdPart;
  camera_move?: PartReference;
  frame_layout?: PartReference;
  transition_in?: PartReference;
  transition_out?: PartReference;
  sfx?: SfxPart[];
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
  // Compositional Architecture: scene-level parts (= UI 2 で編集対象)
  scene_parts?: SceneParts;
  // Layer 1 (clip library) identity + annotation
  identity?: Identity;
  annotation?: Annotation;
  // クライアント側で付与される React key 用 ID。API 送信時に strip される。
  _uid?: string;
}

// Compositional Architecture: global_parts (= screenplay-wide パーツ)。
export interface GlobalPartsBgm {
  path: string;
  ducking_curve?: number | [number, number][];
}
export interface GlobalPartsCard {
  id: string;
  duration_sec: number;
  params?: Record<string, unknown>;
}
export interface GlobalParts {
  filter_preset?: PartReference;
  intro_card?: GlobalPartsCard;
  outro_card?: GlobalPartsCard;
  bgm?: GlobalPartsBgm;
}

export interface AbstractScreenplay {
  caption: string;
  scenes: AbstractScene[];
  // この動画に登場させる人物の characters/<id>.png キーのリスト。
  // シーンの登場人物・話者の候補として使われる。
  featured_characters?: string[];
  // analyze 時に Claude が割り振った匿名 speaker_N を実 character ref に
  // マッピングする辞書。compose で line.speaker と scene の登場人物を解決する。
  speaker_to_ref?: Record<string, string>;
  // Compositional Architecture: screenplay-wide parts (= UI 3 で編集対象)
  global_parts?: GlobalParts;
  // future-proof で broadly に許容する。
  [k: string]: unknown;
}

export interface AbstractDiagnostics {
  unmapped_speakers: string[];
  scenes_without_location: number[];
  scenes_without_characters: number[];
  invalid_camera_distance: { scene_idx: number; value: string }[];
  unknown_character_refs: {
    featured: string[];
    speaker_to_ref: { speaker: string; ref: string }[];
    character_selection: { scene_idx: number; ref: string }[];
    speaker: { scene_idx: number; line_idx: number; ref: string }[];
  };
}

export interface AbstractScreenplayResponse {
  screenplay_path: string;
  abstract: AbstractScreenplay;
}

// ─── Stage 3 (BG) / Stage 4 (Kling) cache decision flow ─────────
//
// 同じ scan / use-cache / queue-fresh / generate-remaining モデルで両 stage を扱う。
// stage 別の差分は CacheCandidate.meta の中身だけ。

export interface CacheQuality {
  blacklisted?: boolean;
  blacklist_reason?: string | null;
  ffprobe_ok?: boolean;
  integrity_ok?: boolean;
  approved_at_origin?: string | null;
  final_render_completed?: boolean;
}

export interface BgCandidateMeta {
  location_ref?: string | null;
  camera_distance?: string | null;
  character_refs?: string[];
  background_prompt_resolved?: string | null;
  created_at?: string | null;
  hit_count?: number | null;
  quality?: CacheQuality;
}

export interface KlingCandidateMeta {
  kling_duration?: number | null;
  original_audio_duration?: number | null;
  location_ref?: string | null;
  camera_distance?: string | null;
  created_at?: string | null;
  hit_count?: number | null;
  quality?: CacheQuality;
}

export interface CacheCandidate<TMeta = unknown> {
  key: string;
  fitness: number;
  warnings: string[];
  meta: TMeta;
}

export type DecisionStatus = "pending" | "cache" | "fresh";

export interface SceneDecision<TMeta = unknown> {
  candidates: CacheCandidate<TMeta>[];
  decision: DecisionStatus;
  decided_key: string | null;
  decided_at: string | null;
  cache_key: string | null;
  diagnostics: string[];
  // Kling 固有 (BG では undefined)
  kling_duration?: number | null;
  final_duration?: number | null;
}

export interface DecisionsResponse<TMeta = unknown> {
  cache_scanned_at: string | null;
  scene_decisions: Record<string, SceneDecision<TMeta>>;
}

export type BgSceneDecision = SceneDecision<BgCandidateMeta>;
export type BgDecisionsResponse = DecisionsResponse<BgCandidateMeta>;
export type KlingSceneDecision = SceneDecision<KlingCandidateMeta>;
export type KlingDecisionsResponse = DecisionsResponse<KlingCandidateMeta>;

export interface CacheEntryBase {
  key: string;
  meta_path: string | null;
  size_bytes: number;
  hit_count: number;
  last_used_at: string | null;
  created_at: string | null;
  location_ref: string | null;
  quality: CacheQuality;
}

export interface BgCacheEntry extends CacheEntryBase {
  image_path: string;
  camera_distance?: string | null;
}

export interface KlingCacheEntry extends CacheEntryBase {
  mp4_path: string;
  kling_duration: number | null;
  original_audio_duration: number | null;
  quality: {
    blacklisted?: boolean;
    blacklist_reason?: string | null;
    ffprobe_ok?: boolean;
    approved_at_origin?: string | null;
    final_render_completed?: boolean;
  };
}

// ─────────────────── Cost Tracking ───────────────────
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
