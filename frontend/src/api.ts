import type {
  ProjectDetail,
  ProjectListItem,
  Progress,
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
  job: (id: string) => http<JobStatus>(`/api/jobs/${id}`),
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
