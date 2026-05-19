// api.ts から抽出 (= §3.1.3 helper 分離)。
//
// 単一 stage 分の cache 操作 API を生成する factory。bg / kling の両方で
// 同じ shape を持つため、stage 引数 + meta/entry 型パラメータで使い回す。
// http クライアントと API_BASE は呼出側 (api.ts) から injection し、循環
// 依存を避ける。

import type {
  BgCandidateMeta,
  BgCacheEntry,
  DecisionsResponse,
  KlingCacheEntry,
  KlingCandidateMeta,
  SceneDecision,
} from "../types";

export interface StageCacheApi<TMeta, TEntry> {
  scanCache: (ts: string) => Promise<DecisionsResponse<TMeta>>;
  decisions: (ts: string) => Promise<DecisionsResponse<TMeta>>;
  useCache: (
    ts: string,
    sceneIdx: number,
    key: string,
  ) => Promise<{ ok: true; decision: "cache"; key: string }>;
  queueFresh: (
    ts: string,
    sceneIdx: number,
  ) => Promise<{ ok: true; decision: "fresh" }>;
  sceneRescan: (
    ts: string,
    sceneIdx: number,
  ) => Promise<{ ok: true; scene_decision: SceneDecision<TMeta> }>;
  decisionsBulk: (
    ts: string,
    action: "all-cache" | "all-fresh",
  ) => Promise<{
    ok: true;
    summary: { adopted: number; queued_fresh: number; errors: unknown[] };
    scene_decisions: Record<string, SceneDecision<TMeta>>;
  }>;
  generateRemaining: (
    ts: string,
  ) => Promise<{ job_id: string; fresh_scenes: number[] }>;
  entries: () => Promise<{ entries: TEntry[] }>;
  blacklist: (key: string, reason: string) => Promise<{ ok: true }>;
  delete: (key: string) => Promise<{ ok: true; deleted: string }>;
  previewUrl: (key: string) => string;
}

type HttpFn = <T>(path: string, init?: RequestInit) => Promise<T>;

export function makeStageCacheApi<TMeta, TEntry>(
  stage: "bg" | "kling",
  previewExt: "png" | "mp4",
  http: HttpFn,
  apiBase: string,
): StageCacheApi<TMeta, TEntry> {
  const stageBase = (ts: string) => `/api/projects/${ts}/stages/${stage}`;
  const cacheBase = `/api/${stage}-cache`;
  return {
    scanCache: (ts) =>
      http<DecisionsResponse<TMeta>>(`${stageBase(ts)}/scan-cache`, {
        method: "POST",
      }),
    decisions: (ts) =>
      http<DecisionsResponse<TMeta>>(`${stageBase(ts)}/decisions`),
    useCache: (ts, sceneIdx, key) =>
      http(`${stageBase(ts)}/scenes/${sceneIdx}/use-cache`, {
        method: "POST",
        body: JSON.stringify({ key }),
      }),
    queueFresh: (ts, sceneIdx) =>
      http(`${stageBase(ts)}/scenes/${sceneIdx}/queue-fresh`, {
        method: "POST",
      }),
    sceneRescan: (ts, sceneIdx) =>
      http(`${stageBase(ts)}/scenes/${sceneIdx}/rescan`, { method: "POST" }),
    decisionsBulk: (ts, action) =>
      http(`${stageBase(ts)}/decisions/bulk`, {
        method: "POST",
        body: JSON.stringify({ action }),
      }),
    generateRemaining: (ts) =>
      http(`${stageBase(ts)}/generate-remaining`, { method: "POST" }),
    entries: () => http<{ entries: TEntry[] }>(`${cacheBase}/entries`),
    blacklist: (key, reason) =>
      http(`${cacheBase}/${key}/blacklist`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    delete: (key) => http(`${cacheBase}/${key}`, { method: "DELETE" }),
    previewUrl: (key) => `${apiBase}${cacheBase}/${key}/preview.${previewExt}`,
  };
}

// 旧 API 互換 (= 既存のテスト / コードが import している)。bgCache / klingCache
// インスタンスを引数で受け取り、それぞれ previewUrl を委譲する。
export const makeKlingCachePreviewUrl =
  (api: { klingCache: StageCacheApi<KlingCandidateMeta, KlingCacheEntry> }) =>
  (key: string): string =>
    api.klingCache.previewUrl(key);

export const makeBgCachePreviewUrl =
  (api: { bgCache: StageCacheApi<BgCandidateMeta, BgCacheEntry> }) =>
  (key: string): string =>
    api.bgCache.previewUrl(key);
