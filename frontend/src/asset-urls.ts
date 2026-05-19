// api.ts から抽出 (= §3.1.3 helper 分離)。
//
// `${API_BASE}/asset/...` 系の純粋 URL 構築関数群。withVersion は
// `?v=<regen_count>` を付けてブラウザ cache を回避するクエリ拡張。
// api.ts 経由で従来 import path を温存するため barrel re-export している。

// 開発・本番とも同一オリジン (= `""`)。env で書き換える運用は無いため固定。
const API_BASE = "";

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
// StageOverlay の primary preview から <video src> として読まれる。
// bumpKey を `?bust=` に渡して再焼き直し後の cache 回避に使う。
export function overlayAssetUrl(ts: string, version?: number | string): string {
  return withVersion(`${API_BASE}/asset/${ts}/overlay`, version);
}

export function finalVersionAssetUrl(
  ts: string,
  filename: string,
  version?: number | string,
): string {
  return withVersion(
    `${API_BASE}/asset/${ts}/final-version/${encodeURIComponent(filename)}`,
    version,
  );
}
export function referenceVideoAssetUrl(sha256: string): string {
  return `${API_BASE}/asset/reference-video/${sha256}`;
}
export function characterAssetUrl(name: string): string {
  return `${API_BASE}/asset/character/${encodeURIComponent(name)}`;
}
export function locationPreviewUrl(
  id: string,
  version?: number | string,
): string {
  return withVersion(
    `${API_BASE}/asset/location/${encodeURIComponent(id)}/preview`,
    version,
  );
}
