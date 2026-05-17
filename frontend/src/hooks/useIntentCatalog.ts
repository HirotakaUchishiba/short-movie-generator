import { useEffect, useState } from "react";

// `/api/intent-catalog` の Response 型 (= routes/intent_catalog.py の出力)
export type IntentEntry = {
  id: string;
  description: string;
  params_schema: Record<string, unknown>;
  valid_contexts: string[];
  deprecated: boolean;
  valid_start_emotions: string[];
  duration_buckets: number[];
  compatible_with: string[];
  motion_intensity_bucket: string | null;
};

export type IntentCatalogStatus = "ok" | "missing" | "parse_error";

export type IntentCatalogResponse = {
  category: "visual_intents";
  // status: yaml の存在 + 解析状況。"missing" = ファイル無し (= deploy 事故)、
  // "parse_error" = ファイル破損。"ok" 以外は entries が空でも warn 表示する。
  status: IntentCatalogStatus;
  // 後方互換: status === "ok" と同義。
  found: boolean;
  entries: IntentEntry[];
};

export type UseIntentCatalogState =
  | { kind: "loading" }
  | { kind: "ready"; data: IntentCatalogResponse }
  | { kind: "error"; message: string };

let _cache: IntentCatalogResponse | null = null;
let _inflight: Promise<IntentCatalogResponse> | null = null;

async function fetchCatalog(): Promise<IntentCatalogResponse> {
  if (_cache) return _cache;
  if (_inflight) return _inflight;
  // api.ts の http() ではなく直接 fetch を使う:
  // module-level の in-flight cache + 早期実行で auth flow と独立に動かす。
  // error 表現は ApiError と同じ shape (`${status}: ${text}`) で throw する。
  _inflight = fetch("/api/intent-catalog")
    .then(async (r) => {
      if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
      return r.json();
    })
    .then((d: IntentCatalogResponse) => {
      _cache = d;
      _inflight = null;
      return d;
    })
    .catch((e) => {
      _inflight = null;
      throw e;
    });
  return _inflight;
}

/** Module-level cache を消す (= テスト用 / 開発時の hot reload 用)。 */
export function resetIntentCatalogCache(): void {
  _cache = null;
  _inflight = null;
}

/**
 * GET /api/intent-catalog を 1 回だけ fetch して全 component で共有する hook。
 * yaml の SSOT は `config/part_registry/visual_intents.yaml`、Python は
 * `routes/intent_catalog.py` がそれを読んで JSON 化する。
 */
export function useIntentCatalog(): UseIntentCatalogState {
  const [state, setState] = useState<UseIntentCatalogState>(
    _cache ? { kind: "ready", data: _cache } : { kind: "loading" },
  );

  useEffect(() => {
    if (_cache) {
      setState({ kind: "ready", data: _cache });
      return;
    }
    let cancelled = false;
    fetchCatalog()
      .then((d) => {
        if (!cancelled) setState({ kind: "ready", data: d });
      })
      .catch((e) => {
        if (!cancelled) setState({ kind: "error", message: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
