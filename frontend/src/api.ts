import type {
  BgmTrack,
  SeTrack,
  SeItem,
  AbstractScreenplay,
  AbstractScreenplayResponse,
  AnalyzeJobDetail,
  BgCacheEntry,
  BgCandidateMeta,
  BgDecisionsResponse,
  BgSceneDecision,
  CharacterMeta,
  QaTagsConfig,
  RejectBody,
  RejectResponse,
  CostEstimate,
  CostMedianRate,
  CostOverallReport,
  CostPricebookResponse,
  CostProjectReport,
  CostStage,
  DecisionsResponse,
  FinalVersion,
  KlingCacheEntry,
  KlingCandidateMeta,
  KlingDecisionsResponse,
  KlingSceneDecision,
  Location,
  ProjectDetail,
  ProjectListItem,
  Progress,
  PublishedPost,
  ReferenceVideo,
  ReferenceVideoUploadResult,
  Screenplay,
  SceneDecision,
  ServerConfig,
  StageName,
  JobStatus,
  TtsPricing,
} from "./types";
import { attachUidsToAbstract, attachUidsToScreenplay, stripUids } from "./uid";

const API_BASE = "";

const PREVIEW_TOKEN: string | undefined = (
  import.meta as { env?: Record<string, string> }
).env?.VITE_PREVIEW_TOKEN;

function authHeader(): Record<string, string> {
  return PREVIEW_TOKEN ? { Authorization: `Bearer ${PREVIEW_TOKEN}` } : {};
}

/**
 * fetch が non-2xx を返したときに http() が throw する error。
 * 旧コード (= `String(err).includes("409")`) との互換のため `message` には
 * `${status}: ${text}` を入れるが、新コードは `err.status` / `err.body` で
 * 分岐すること (= `error_code` field を含む JSON body をパース済みで持つ)。
 */
export class ApiError extends Error {
  status: number;
  body: unknown;
  bodyText: string;

  constructor(status: number, bodyText: string, body: unknown) {
    super(`${status}: ${bodyText}`);
    this.name = "ApiError";
    this.status = status;
    this.bodyText = bodyText;
    this.body = body;
  }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API_BASE + path, {
    headers: {
      "Content-Type": "application/json",
      ...authHeader(),
      ...(init?.headers || {}),
    },
    ...init,
  });
  if (!r.ok) {
    const text = await r.text();
    let parsed: unknown = undefined;
    try {
      parsed = JSON.parse(text);
    } catch {
      // 非 JSON body はそのまま文字列で持つ
    }
    throw new ApiError(r.status, text, parsed);
  }
  return r.json();
}

function applyAuthToXhr(xhr: XMLHttpRequest): void {
  if (PREVIEW_TOKEN) {
    xhr.setRequestHeader("Authorization", `Bearer ${PREVIEW_TOKEN}`);
  }
}

export const api = {
  config: () => http<ServerConfig>("/api/config"),
  setModel: (model: string) =>
    http<{ ok: true; tts_pricing: TtsPricing }>("/api/config/model", {
      method: "POST",
      body: JSON.stringify({ model }),
    }),
  setSpeed: (speed: number) =>
    http<{ ok: true; tts_pricing: TtsPricing }>("/api/config/speed", {
      method: "POST",
      body: JSON.stringify({ speed }),
    }),
  setSilences: (body: { enabled?: boolean; max_ms?: number }) =>
    http<{ ok: true; tts_pricing: TtsPricing }>("/api/config/silences", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  qaTags: () => http<QaTagsConfig>("/api/config/qa-tags"),
  projects: () =>
    http<{ projects: ProjectListItem[]; screenplays: string[] }>(
      "/api/projects",
    ),
  createProject: (screenplay_name: string, analyzeJobId?: string) =>
    http<{ timestamp: string; current_stage: StageName }>("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        screenplay_name,
        ...(analyzeJobId ? { analyze_job_id: analyzeJobId } : {}),
      }),
    }),
  project: async (ts: string) => {
    const r = await http<ProjectDetail>(`/api/projects/${ts}`);
    if (r.screenplay) attachUidsToScreenplay(r.screenplay);
    return r;
  },
  progress: (ts: string) =>
    http<{ progress: Progress; current_stage: StageName | null }>(
      `/api/projects/${ts}/progress`,
    ),
  approve: (ts: string, stage: StageName) =>
    http<{ ok: true; approved_stage: StageName; next_stage: StageName | null }>(
      `/api/projects/${ts}/approve`,
      { method: "POST", body: JSON.stringify({ stage }) },
    ),
  reject: (ts: string, body: RejectBody) =>
    http<RejectResponse>(`/api/projects/${ts}/reject`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  runNext: (ts: string) =>
    http<{ job_id: string }>(`/api/projects/${ts}/run-next`, {
      method: "POST",
    }),
  regen: (
    ts: string,
    body: {
      stage: StageName;
      scene_idx?: number;
      line_idx?: number;
      force?: boolean;
      force_no_cache?: boolean;
    },
  ) =>
    http<{ job_id: string }>(`/api/projects/${ts}/regen`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  bgCacheInfo: (ts: string, sceneIdx: number) =>
    http<{
      cache_key: string;
      cached: boolean;
      hit_count?: number;
      created_at?: string;
      last_used_at?: string;
    }>(`/api/projects/${ts}/scenes/${sceneIdx}/bg-cache-info`),
  saveScreenplay: (ts: string, screenplay: Screenplay) =>
    http<{ ok: true }>(`/api/projects/${ts}/screenplay`, {
      method: "PUT",
      body: JSON.stringify({ screenplay: stripUids(screenplay) }),
    }),
  listBgm: () => http<{ bgm: BgmTrack[] }>(`/api/bgm`),
  setBgm: (
    ts: string,
    body: { id: string; volume?: number; ducking?: boolean },
  ) =>
    http<{ bgm: { id: string; volume: number; ducking: boolean } }>(
      `/api/projects/${ts}/bgm`,
      { method: "PUT", body: JSON.stringify(body) },
    ),
  listSe: () => http<{ se: SeTrack[] }>(`/api/se`),
  setSe: (ts: string, items: SeItem[]) =>
    http<{ se: { items: SeItem[] } }>(`/api/projects/${ts}/se`, {
      method: "PUT",
      body: JSON.stringify({ items }),
    }),
  autoSe: (ts: string) =>
    http<{ se: { items: SeItem[]; auto_generated_at?: string } }>(
      `/api/projects/${ts}/se/auto`,
      { method: "POST" },
    ),
  // Server-side merge: 特定 line の指定フィールドだけ更新。
  // 並行 patch しても他 line を上書きしない (race condition 回避)。
  // patch.<field> = null でフィールド削除。
  patchLine: (
    ts: string,
    sceneIdx: number,
    lineIdx: number,
    patch: Record<string, unknown>,
  ) =>
    http<{ ok: true }>(`/api/projects/${ts}/lines/${sceneIdx}/${lineIdx}`, {
      method: "PATCH",
      body: JSON.stringify({ patch: stripUids(patch) }),
    }),
  patchScreenplayMeta: (ts: string, patch: Record<string, unknown>) =>
    http<{ ok: true }>(`/api/projects/${ts}/screenplay-meta`, {
      method: "PATCH",
      body: JSON.stringify({ patch }),
    }),
  // characters/ 配下の利用可能な ref 一覧 (拡張子なし)
  listCharacters: () => http<{ characters: string[] }>("/api/characters"),
  // グローバル locations/<id>.json
  listLocations: () => http<{ locations: Location[] }>("/api/locations"),
  getLocation: (id: string) => http<Location>(`/api/locations/${id}`),
  createLocation: (loc: Location) =>
    http<Location>("/api/locations", {
      method: "POST",
      body: JSON.stringify(loc),
    }),
  updateLocation: (id: string, loc: Location) =>
    http<Location>(`/api/locations/${id}`, {
      method: "PUT",
      body: JSON.stringify(loc),
    }),
  deleteLocation: (id: string) =>
    http<{ id: string; deleted: true }>(`/api/locations/${id}`, {
      method: "DELETE",
    }),
  // characters/<id>.json (= 衣装込みキャラの voice メタ)
  listCharacterMetas: () =>
    http<{ character_metas: CharacterMeta[]; image_ids: string[] }>(
      "/api/character-metas",
    ),
  getCharacterMeta: (id: string) =>
    http<CharacterMeta>(`/api/character-metas/${id}`),
  updateCharacterMeta: (id: string, meta: CharacterMeta) =>
    http<CharacterMeta>(`/api/character-metas/${id}`, {
      method: "PUT",
      body: JSON.stringify(meta),
    }),
  deleteCharacterMeta: (id: string) =>
    http<{ id: string; deleted: true }>(`/api/character-metas/${id}`, {
      method: "DELETE",
    }),
  presets: () =>
    http<{
      libraries: Record<string, Record<string, string>>;
      labels_ja: Record<string, Record<string, string>>;
      category_labels_ja: Record<string, string>;
      emotion_default_preset_ids: Record<string, Record<string, string>>;
    }>("/api/presets"),
  ttsSource: (ts: string) =>
    http<{
      text: string;
      char_count: number;
      separator: string;
      line_specs: {
        scene_idx: number;
        line_idx: number;
        char_start: number;
        char_end: number;
      }[];
    }>(`/api/projects/${ts}/tts-source`),
  composedPrompts: (ts: string, sceneIdx: number) =>
    http<{
      scene_idx: number;
      background_prompt: string;
      animation_prompt: string;
    }>(`/api/projects/${ts}/scenes/${sceneIdx}/composed-prompts`),
  job: (id: string) => http<JobStatus>(`/api/jobs/${id}`),

  // ─── reference videos (analyze 用) ──────────────
  listReferenceVideos: () =>
    http<{ reference_videos: ReferenceVideo[] }>("/api/reference_videos"),
  uploadReferenceVideo: (
    file: File,
    onProgress?: (pct: number) => void,
  ): Promise<ReferenceVideoUploadResult> => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const fd = new FormData();
      fd.append("file", file);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(e.loaded / e.total);
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch (e) {
            reject(e instanceof Error ? e : new Error(String(e)));
          }
        } else {
          reject(new Error(`${xhr.status}: ${xhr.responseText}`));
        }
      };
      xhr.onerror = () => reject(new Error("network error"));
      xhr.open("POST", `${API_BASE}/api/reference_videos`);
      applyAuthToXhr(xhr);
      xhr.send(fd);
    });
  },
  deleteReferenceVideo: (sha256: string, force = false) =>
    http<{ sha256: string; deleted: boolean; force?: boolean }>(
      `/api/reference_videos/${sha256}${force ? "?force=true" : ""}`,
      { method: "DELETE" },
    ),

  // ─── 主導フロー: 参考動画 → project + analyze (= Phase B) ────
  createProjectFromReferenceVideo: (
    file: File,
    options: { fps?: number } = {},
    onProgress?: (pct: number) => void,
  ): Promise<{ ts: string; analyze_job_id: string }> => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const fd = new FormData();
      fd.append("reference_video", file);
      if (options.fps != null) fd.append("fps", String(options.fps));
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(e.loaded / e.total);
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch (e) {
            reject(e instanceof Error ? e : new Error(String(e)));
          }
        } else {
          let body: unknown;
          try {
            body = JSON.parse(xhr.responseText);
          } catch {
            // body 取れなくても ApiError は返す
          }
          reject(new ApiError(xhr.status, xhr.responseText, body));
        }
      };
      xhr.onerror = () => reject(new Error("network error"));
      xhr.open("POST", `${API_BASE}/api/projects/from-reference-video`);
      applyAuthToXhr(xhr);
      xhr.send(fd);
    });
  },
  retryAnalyzeForProject: (ts: string) =>
    http<{ ok: true; new_analyze_job_id: string }>(
      `/api/projects/${ts}/retry-analyze`,
      { method: "POST" },
    ),
  deleteProject: (ts: string) =>
    http<{ ts: string; deleted: true }>(`/api/projects/${ts}`, {
      method: "DELETE",
    }),

  bulkDeleteProjects: (tsList: string[]) =>
    http<{
      deleted: string[];
      failed: Array<{ ts: string; error_code: string; message: string }>;
    }>("/api/projects/bulk-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ts_list: tsList }),
    }),

  // ─── analyze ジョブ ─────────────────────────────
  // ジョブの作成は POST /api/projects/from-reference-video を使う
  // (= 旧 createAnalyzeJob / listAnalyzeJobs は Phase E で削除)。
  // ここに残るのは AnalyzeStage0Page から既存ジョブを操作する経路のみ。
  getAnalyzeJob: (id: string) =>
    http<AnalyzeJobDetail>(`/api/screenplay/analyze/${id}`),
  confirmAnalyzeJob: (id: string) =>
    http<{ ok: true }>(`/api/screenplay/analyze/${id}/confirm`, {
      method: "POST",
    }),
  cancelAnalyzeJob: (id: string) =>
    http<{ ok: true }>(`/api/screenplay/analyze/${id}`, { method: "DELETE" }),
  analyzeJobEventSource: (id: string): EventSource =>
    new EventSource(`${API_BASE}/api/screenplay/analyze/${id}/events`),

  // ─── project snapshot (Stage 1 素材編集) ──────────
  getProjectAbstract: async (ts: string) => {
    const r = await http<AbstractScreenplayResponse>(
      `/api/projects/${ts}/abstract`,
    );
    if (r.abstract) attachUidsToAbstract(r.abstract);
    return r;
  },
  putProjectAbstract: (ts: string, abstract: AbstractScreenplay) =>
    http<{ screenplay_path: string; scenes: number }>(
      `/api/projects/${ts}/abstract`,
      {
        method: "PUT",
        body: JSON.stringify({ abstract: stripUids(abstract) }),
      },
    ),

  // ─── scene 境界の手動再定義 (TTS 完了後) ──────────
  // line のテキスト・順序は変えず、scene の区切り位置だけを動かす。
  // tts_full.mp3 は再利用されるので ElevenLabs API は呼ばれない。
  // 副作用: bg / kling / scene / overlay 系は全削除 + 承認解除。
  applySceneBoundaries: (ts: string, lineBoundaries: number[]) =>
    http<{ ok: true; scenes: number; lines: number }>(
      `/api/projects/${ts}/scene-boundaries`,
      {
        method: "POST",
        body: JSON.stringify({ line_boundaries: lineBoundaries }),
      },
    ),

  // ─── Stage 3 BG / Stage 4 Kling cache decision flow ──────────
  // bg / kling は makeStageCacheApi で生成される (= scan / use-cache / queue-fresh /
  // generate-remaining / entries / blacklist / delete を提供)。詳細は下記参照。
  bgCache: undefined as unknown as ReturnType<
    typeof makeStageCacheApi<BgCandidateMeta, BgCacheEntry>
  >,
  klingCache: undefined as unknown as ReturnType<
    typeof makeStageCacheApi<KlingCandidateMeta, KlingCacheEntry>
  >,

  // ─── Stage 8 final import / Stage 9 publish ──────────
  listFinals: (ts: string) =>
    http<{ final_versions: FinalVersion[] }>(`/api/projects/${ts}/final`),
  setCanonicalFinal: (ts: string, filename: string) =>
    http<{ final_version: FinalVersion }>(
      `/api/projects/${ts}/final/${encodeURIComponent(filename)}/canonical`,
      { method: "POST" },
    ),
  deleteFinal: (ts: string, filename: string) =>
    http<{ ok: true; deleted: string }>(
      `/api/projects/${ts}/final/${encodeURIComponent(filename)}`,
      { method: "DELETE" },
    ),
  publish: (
    ts: string,
    body: {
      platform: "youtube" | "instagram" | "tiktok";
      privacy?: "private" | "unlisted" | "public";
    },
  ) =>
    http<{ job_id: string }>(`/api/projects/${ts}/publish`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  publishHistory: (ts: string) =>
    http<{ published_posts: PublishedPost[] }>(
      `/api/projects/${ts}/publish-history`,
    ),

  // cost: 実体は ./api/cost.ts (= §3.1.3 で分離)。bgCache と同じ pattern で
  // placeholder 予約 → 下で makeCostApi(http) を代入する。
  cost: undefined as unknown as ReturnType<typeof makeCostApi>,
};

// ─── Cost Tracking (実コスト履歴ベースの動的見積もり + レポート) ──────────
import { makeCostApi } from "./api/cost";

api.cost = makeCostApi(http);

// ─── stage cache API factory (= 単一 stage 分の cache 操作を生成) ──────────
// 実体は ./api/stage-cache.ts に移管 (= §3.1.3)。http / API_BASE を inject。
import { makeStageCacheApi } from "./api/stage-cache";

api.bgCache = makeStageCacheApi<BgCandidateMeta, BgCacheEntry>(
  "bg",
  "png",
  http,
  API_BASE,
);
api.klingCache = makeStageCacheApi<KlingCandidateMeta, KlingCacheEntry>(
  "kling",
  "mp4",
  http,
  API_BASE,
);

// 旧 API 互換 (= 既存のテスト / コードが klingCachePreviewUrl を import している)
export function klingCachePreviewUrl(key: string): string {
  return api.klingCache.previewUrl(key);
}
export function bgCachePreviewUrl(key: string): string {
  return api.bgCache.previewUrl(key);
}

// 型を再エクスポート (= 必要な consumer 側で安く使えるように)
export type {
  BgSceneDecision,
  KlingSceneDecision,
  BgDecisionsResponse,
  KlingDecisionsResponse,
};

// asset URL 関数群は ./asset-urls.ts に移管済 (= §3.1.3)。
// 既存 import path (= `from "../api"`) を破壊しないよう re-export する。
export {
  bgAssetUrl,
  characterAssetUrl,
  finalVersionAssetUrl,
  klingAssetUrl,
  locationPreviewUrl,
  overlayAssetUrl,
  referenceVideoAssetUrl,
  sceneAssetUrl,
  sceneAudioAssetUrl,
  sceneTrimAssetUrl,
  ttsAssetUrl,
  ttsMergedAssetUrl,
} from "./asset-urls";
