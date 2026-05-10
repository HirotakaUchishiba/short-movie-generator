import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { RenderPlan } from "../../remotion/schemas/renderPlan";

// Stage 6 UI が Remotion <Player> を駆動するための render plan を取得する hook。
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §5.5

export type UseRenderPlanState =
  | { kind: "loading" }
  | { kind: "ready"; plan: RenderPlan }
  | { kind: "not_ready"; message: string }
  | { kind: "error"; message: string };

/**
 * `/api/projects/<TS>/render-plan` を fetch する hook。
 *
 * 引数 `bumpKey` は「字幕編集を保存した後、再 fetch を促したい」ときに値を変えると
 * 再フェッチがかかるトリガ (= 既存の overlay regen_count を流用すれば OK)。
 *
 * Stage 5 完了前 (= 409) は ready ではなく `not_ready` を返す。
 */
export function useRenderPlan(
  ts: string,
  bumpKey: number = 0,
): UseRenderPlanState {
  const [state, setState] = useState<UseRenderPlanState>({ kind: "loading" });
  const reqIdRef = useRef(0);

  useEffect(() => {
    if (!ts) return;
    const reqId = ++reqIdRef.current;
    setState({ kind: "loading" });

    api
      .renderPlan(ts)
      .then((res) => {
        if (reqId !== reqIdRef.current) return;
        setState({ kind: "ready", plan: res.plan });
      })
      .catch((err: unknown) => {
        if (reqId !== reqIdRef.current) return;
        // 409 (= scenes 未完了 / scene_<S>.mp4 無し) は not_ready 扱い。
        // backend からは {error_code, message} が返るので code 経由で分岐する
        // (= 旧 `String(err).includes("409")` の string match に頼らない)。
        if (err instanceof ApiError && err.status === 409) {
          const body = (err.body ?? {}) as {
            message?: string;
            error_code?: string;
          };
          const message =
            body.message ??
            "Stage 5 (scene 合成) が完了するとリアルタイムプレビューが利用可能になります";
          setState({ kind: "not_ready", message });
        } else {
          setState({ kind: "error", message: String(err) });
        }
      });
  }, [ts, bumpKey]);

  return state;
}
