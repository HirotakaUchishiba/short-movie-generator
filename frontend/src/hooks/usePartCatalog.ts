import { useEffect, useState } from "react";

// `/api/parts/catalog` の Response 型 (= routes/part_catalog.py の出力)
export type PartParamSchema = Record<string, unknown>;

export type PartEntry = {
  id: string;
  description: string;
  params_schema: PartParamSchema;
  valid_contexts: ("scene" | "global" | string)[];
  deprecated: boolean;
  // visual_intents 専用 (= 他カテゴリでは [])
  valid_start_emotions: string[];
  duration_buckets: number[];
  compatible_with: string[];
  motion_intensity_bucket: string | null;
};

export type PartCategoryDoc = {
  category: string;
  version?: number;
  found: boolean;
  entries: PartEntry[];
};

export type PartCatalogResponse = {
  categories: Record<string, PartCategoryDoc>;
};

export type UsePartCatalogState =
  | { kind: "loading" }
  | { kind: "ready"; data: PartCatalogResponse }
  | { kind: "error"; message: string };

let _cache: PartCatalogResponse | null = null;
let _inflight: Promise<PartCatalogResponse> | null = null;

async function fetchCatalog(): Promise<PartCatalogResponse> {
  if (_cache) return _cache;
  if (_inflight) return _inflight;
  _inflight = fetch("/api/parts/catalog")
    .then(async (r) => {
      if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
      return r.json();
    })
    .then((d: PartCatalogResponse) => {
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
export function resetPartCatalogCache(): void {
  _cache = null;
  _inflight = null;
}

/**
 * GET /api/parts/catalog を 1 回だけ fetch して全 component で共有する hook。
 * yaml の SSOT は `config/part_registry/*.yaml`、Python は
 * `routes/part_catalog.py` がそれを読んで JSON 化する。
 *
 * 設計 ref: docs/plannings/2026-05-10_compositional-architecture.md §4
 */
export function usePartCatalog(): UsePartCatalogState {
  const [state, setState] = useState<UsePartCatalogState>(
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

/** 特定 category の entries 配列だけを返すショートカット。 */
export function useCategoryEntries(category: string): PartEntry[] {
  const state = usePartCatalog();
  if (state.kind !== "ready") return [];
  const cat = state.data.categories[category];
  if (!cat || !cat.found) return [];
  return cat.entries.filter((e) => !e.deprecated);
}
