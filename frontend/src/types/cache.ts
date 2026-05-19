// types.ts から抽出 (= §3.1.3 type 分離)。
//
// Stage 3 (BG) / Stage 4 (Kling) の cache decision flow と cache entry の型。
// 同じ scan / use-cache / queue-fresh / generate-remaining モデルで両 stage
// を扱う。stage 別の差分は CacheCandidate.meta の中身だけ。

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
