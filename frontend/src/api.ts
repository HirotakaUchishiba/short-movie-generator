import type {
  AnalyzeJob,
  AnalyzeJobDetail,
  AnalyzeOptions,
  ProjectDetail,
  ProjectListItem,
  Progress,
  ReferenceVideo,
  ReferenceVideoUploadResult,
  Screenplay,
  ServerConfig,
  StageName,
  JobStatus,
  TtsPricing,
} from "./types";

const API_BASE = "";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status}: ${text}`);
  }
  return r.json();
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
  projects: () =>
    http<{ projects: ProjectListItem[]; screenplays: string[] }>(
      "/api/projects",
    ),
  createProject: (screenplay_name: string) =>
    http<{ timestamp: string; current_stage: StageName }>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ screenplay_name }),
    }),
  project: (ts: string) => http<ProjectDetail>(`/api/projects/${ts}`),
  progress: (ts: string) =>
    http<{ progress: Progress; current_stage: StageName | null }>(
      `/api/projects/${ts}/progress`,
    ),
  approve: (ts: string, stage: StageName) =>
    http<{ ok: true; approved_stage: StageName; next_stage: StageName | null }>(
      `/api/projects/${ts}/approve`,
      { method: "POST", body: JSON.stringify({ stage }) },
    ),
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
    },
  ) =>
    http<{ job_id: string }>(`/api/projects/${ts}/regen`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  saveScreenplay: (ts: string, screenplay: Screenplay) =>
    http<{ ok: true }>(`/api/projects/${ts}/screenplay`, {
      method: "PUT",
      body: JSON.stringify({ screenplay }),
    }),
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
      body: JSON.stringify({ patch }),
    }),
  patchScene: (ts: string, sceneIdx: number, patch: Record<string, unknown>) =>
    http<{ ok: true }>(`/api/projects/${ts}/scenes/${sceneIdx}`, {
      method: "PATCH",
      body: JSON.stringify({ patch }),
    }),
  patchScreenplayMeta: (ts: string, patch: Record<string, unknown>) =>
    http<{ ok: true }>(`/api/projects/${ts}/screenplay-meta`, {
      method: "PATCH",
      body: JSON.stringify({ patch }),
    }),
  presets: () =>
    http<{
      libraries: Record<string, Record<string, string>>;
      labels_ja: Record<string, Record<string, string>>;
      category_labels_ja: Record<string, string>;
      scene_tags: string[];
      scene_tag_labels_ja: Record<string, string>;
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
  previewRevisePrompt: (
    ts: string,
    sceneIdx: number,
    field: "background_prompt" | "animation_prompt",
    instructionJa: string,
  ) =>
    http<{
      scene_idx: number;
      field: "background_prompt" | "animation_prompt";
      previous: string;
      revised: string;
      model: string;
    }>(`/api/projects/${ts}/scenes/${sceneIdx}/revise-prompt`, {
      method: "POST",
      body: JSON.stringify({
        action: "preview",
        field,
        instruction_ja: instructionJa,
      }),
    }),
  applyRevisePrompt: (
    ts: string,
    sceneIdx: number,
    field: "background_prompt" | "animation_prompt",
    revised: string,
    instructionJa: string,
  ) =>
    http<{
      scene_idx: number;
      field: "background_prompt" | "animation_prompt";
      applied: boolean;
      revised: string;
    }>(`/api/projects/${ts}/scenes/${sceneIdx}/revise-prompt`, {
      method: "POST",
      body: JSON.stringify({
        action: "apply",
        field,
        revised,
        instruction_ja: instructionJa,
      }),
    }),
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
      xhr.send(fd);
    });
  },
  deleteReferenceVideo: (sha256: string, force = false) =>
    http<{ sha256: string; deleted: boolean; force?: boolean }>(
      `/api/reference_videos/${sha256}${force ? "?force=true" : ""}`,
      { method: "DELETE" },
    ),

  // ─── analyze ジョブ ─────────────────────────────
  createAnalyzeJob: (video_sha256: string, options: AnalyzeOptions = {}) =>
    http<{ job_id: string }>("/api/screenplay/analyze", {
      method: "POST",
      body: JSON.stringify({ video_sha256, options }),
    }),
  listAnalyzeJobs: () =>
    http<{ jobs: AnalyzeJob[] }>("/api/screenplay/analyze"),
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
};

function withVersion(url: string, v?: number | string): string {
  if (v === undefined || v === null) return url;
  return `${url}?v=${encodeURIComponent(String(v))}`;
}

export function ttsAssetUrl(
  ts: string,
  scene: number,
  line: number,
  version?: number | string,
): string {
  return withVersion(`${API_BASE}/asset/${ts}/tts/${scene}/${line}`, version);
}
export function ttsMergedAssetUrl(
  ts: string,
  version?: number | string,
): string {
  return withVersion(`${API_BASE}/asset/${ts}/tts-merged`, version);
}
export function bgAssetUrl(
  ts: string,
  scene: number,
  version?: number | string,
): string {
  return withVersion(`${API_BASE}/asset/${ts}/bg/${scene}`, version);
}
export function klingAssetUrl(
  ts: string,
  scene: number,
  version?: number | string,
): string {
  return withVersion(`${API_BASE}/asset/${ts}/kling/${scene}`, version);
}
export function sceneTrimAssetUrl(
  ts: string,
  scene: number,
  version?: number | string,
): string {
  return withVersion(`${API_BASE}/asset/${ts}/scene-trim/${scene}`, version);
}
export function sceneAssetUrl(
  ts: string,
  scene: number,
  version?: number | string,
): string {
  return withVersion(`${API_BASE}/asset/${ts}/scene/${scene}`, version);
}
export function sceneAudioAssetUrl(
  ts: string,
  scene: number,
  version?: number | string,
): string {
  return withVersion(`${API_BASE}/asset/${ts}/scene-audio/${scene}`, version);
}
export function overlayAssetUrl(ts: string, version?: number | string): string {
  return withVersion(`${API_BASE}/asset/${ts}/overlay`, version);
}
export function finalAssetUrl(ts: string, version?: number | string): string {
  return withVersion(`${API_BASE}/asset/${ts}/final`, version);
}
