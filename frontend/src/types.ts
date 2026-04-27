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
  pitch_hz_mean?: number;
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
  pause_before?: number;
  breath_before?: boolean;
  speaker?: string;
  silence_after_ms?: number;
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
  time?: string;
  label?: string;
  duration: number;
  background_prompt?: string;
  animation_prompt?: string;
  character_refs?: string[];
  characters?: CharacterDef[];
  wardrobe?: Wardrobe;
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
  title_overlay?: string;
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
