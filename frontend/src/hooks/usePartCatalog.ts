import { useEffect, useState } from "react";

// `/api/parts/catalog` の Response 型 (= routes/part_catalog.py の出力)
export type PartParamSchema = Record<string, unknown>;

export type PartEntry = {
  id: string;
  description: string;
  params_schema: PartParamSchema;
  valid_contexts: ("scene" | "global" | string)[];
  deprecated: boolean;
  // 以下 4 つは visual_intents 専用フィールド。category=visual_intents 以外
  // では backend が omit するため optional。
  valid_start_emotions?: string[];
  duration_buckets?: number[];
  compatible_with?: string[];
  motion_intensity_bucket?: string | null;
};

export type PartCategoryStatus = "ok" | "missing" | "parse_error";

export type PartCategoryDoc = {
  category: string;
  // status: yaml の存在 + 解析状況。"missing" = ファイル無し (= deploy 事故)、
  // "parse_error" = ファイル破損。"ok" 以外は entries が空でも warn 表示する。
  status: PartCategoryStatus;
  // 後方互換: 旧 frontend は found を見ていた。status === "ok" と同義。
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
  // api.ts の http() ではなく直接 fetch を使う理由:
  //   - usePartCatalog は app shell 起動の最初期に走り、このタイミングでは
  //     authHeader() の VITE_PREVIEW_TOKEN はまだ環境変数からのみ参照可能で
  //     api.ts と同じなので問題ないが、PartCatalog だけは module-level の
  //     in-flight cache を持つ独自フローのため wrap せず直接 fetch している
  //   - ただし error 表現は ApiError と同じ shape (`${status}: ${text}`) で
  //     throw して呼出側の `String(e)` 互換を保つ
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
  // status === "ok" 以外 (= missing / parse_error) は entries が空とみなす。
  // backend が "missing" と "parse_error" を区別するので、UI で warn を出したい
  // 場合は useCategoryStatus を別途使う。
  if (!cat || cat.status !== "ok") return [];
  return cat.entries.filter((e) => !e.deprecated);
}

/** 特定 category の status (= "ok" / "missing" / "parse_error") を返す。
 * deploy 事故と yaml 破損を区別したい IntentCatalog 等の管理画面で使う。 */
export function useCategoryStatus(category: string): PartCategoryStatus | null {
  const state = usePartCatalog();
  if (state.kind !== "ready") return null;
  const cat = state.data.categories[category];
  return cat?.status ?? "missing";
}
