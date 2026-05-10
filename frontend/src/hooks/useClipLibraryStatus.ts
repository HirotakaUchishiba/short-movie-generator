import { useEffect, useState } from "react";

// `/api/projects/<ts>/clip-library-status` の Response 型
export type ClipSceneStatus = {
  scene_idx: number;
  has_identity: boolean;
  satisfied: boolean;
  entry_id?: string;
  pool_size?: number;
};

export type ClipLibraryStatusResponse = {
  enabled: boolean;
  scenes: ClipSceneStatus[];
};

export type UseClipLibraryStatusState =
  | { kind: "loading" }
  | { kind: "ready"; data: ClipLibraryStatusResponse }
  | { kind: "error"; message: string };

/**
 * 指定 project の各 scene が clip_library hit するかを判定する hook。
 * Stage 3 (BG) / Stage 4 (Kling) の UI で hit / cold path のバッジ表示に使う。
 *
 * 設計 ref: docs/plannings/2026-05-10_compositional-architecture.md §3
 */
export function useClipLibraryStatus(
  ts: string,
  bumpKey: number = 0,
): UseClipLibraryStatusState {
  const [state, setState] = useState<UseClipLibraryStatusState>({
    kind: "loading",
  });

  useEffect(() => {
    if (!ts) return;
    let cancelled = false;
    setState({ kind: "loading" });
    fetch(`/api/projects/${ts}/clip-library-status`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
        return r.json();
      })
      .then((d: ClipLibraryStatusResponse) => {
        if (!cancelled) setState({ kind: "ready", data: d });
      })
      .catch((e) => {
        if (!cancelled) setState({ kind: "error", message: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [ts, bumpKey]);

  return state;
}
