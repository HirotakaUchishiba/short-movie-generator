export type StageName =
  | "script"
  | "tts"
  | "bg"
  | "kling"
  | "scene"
  | "overlay"
  | "final";

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
  silence_after_ms?: number;
  subtitles?: SubtitleChunk[];
  hidden?: boolean;
}

export interface CharacterDef {
  name?: string;
  role?: string;
  ref?: string;
  outfit?: string;
}

export interface Wardrobe {
  identifier?: string;
  top?: string;
  bottom?: string;
  accessories?: string;
  hair?: string;
}

export interface Scene {
  label?: string;
  duration: number;
  background_prompt?: string;
  animation_prompt?: string;
  character_refs?: string[];
  characters?: CharacterDef[];
  wardrobe?: Wardrobe;
  location_ref?: string;
  facial_expression?: string;
  hand_gesture?: string;
  lipsync?: boolean;
  lines?: Line[];
  tags?: string[];
  emotion_cue_overrides?: Record<string, string>;
}

export interface ScopedAugmentation {
  id?: string;
  scope: { tag?: string; scene_idx?: number[] };
  elements: string[];
}

export interface Screenplay {
  caption?: string;
  audio_mode?: "voiced" | "silent";
  bgm_path?: string;
  bgm_volume_db?: number;
  subtitle_y_from_bottom?: number;
  wardrobe_continuity?: Record<string, string>;
  scoped_augmentations?: ScopedAugmentation[];
  scenes: Scene[];
}

export interface ProjectListItem {
  timestamp: string;
  screenplay_name: string;
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
}

export interface VoiceLibraryEntry {
  voice_id: string;
  name?: string;
  gender?: string;
  age?: string;
  language?: string;
}

export interface EmotionPreset {
  stability?: number;
  style?: number;
  similarity_boost?: number;
  rate_pct?: number;
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
  plan_label: string;
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
  emotion_presets: Record<string, EmotionPreset>;
  emotion_intensities: string[];
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
  cost_usd: number;
  cost_breakdown: Record<string, number>;
}

// ─── VideoStyle (抽象台本合成テンプレ) ─────────

export interface VideoStyleCharacter {
  name: string;
  role: string;
  ref: string;
  voice_overrides?: Record<string, unknown>;
}

export interface VideoStyleLocation {
  decor: string;
  lighting: string;
  color_palette: string;
  props: string;
  camera_distance: "close-up" | "medium-close" | "medium" | "wide";
}

export interface VideoStyle {
  name: string;
  format: "narrator" | "dialogue";
  characters: VideoStyleCharacter[];
  wardrobe_continuity: Record<string, string>;
  default_wardrobe: string | null;
  location_continuity: Record<string, VideoStyleLocation>;
  default_location: string | null;
  default_tags: string[];
  scoped_augmentations: unknown[];
  animation_style: "subtle" | "standard" | "expressive";
}

export interface SceneOverride {
  wardrobe?: string;
  location_ref?: string;
  tags?: string[];
}

export interface ComposeResult {
  screenplay_path: string;
  style_name: string;
  scenes: number;
}
