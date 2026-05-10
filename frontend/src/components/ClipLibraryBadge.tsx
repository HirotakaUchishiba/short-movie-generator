import type { ClipSceneStatus } from "../hooks/useClipLibraryStatus";

/**
 * 1 scene の clip_library 状態をバッジ表示する小さな共通コンポーネント。
 * Stage 3 (BG) / Stage 4 (Kling) の各 scene カードに置く。
 *
 * 表示パターン:
 *   - 未対象: identity 無し scene (= バッジ非表示で何も出さない)
 *   - HIT:    緑バッジ「📦 clip lib HIT (entry: ...)」
 *   - MISS:   橙バッジ「⚠️ clip lib MISS (cold path = AI 課金)」
 *   - DISABLED: 灰バッジ「💤 CLIP_LIBRARY_ENABLED=0 (= 経路 OFF)」
 *
 * 設計 ref: docs/plannings/2026-05-10_compositional-architecture.md §3
 */
export default function ClipLibraryBadge({
  status,
  enabled,
}: {
  status?: ClipSceneStatus;
  enabled?: boolean;
}) {
  if (!status) return null;
  if (!status.has_identity) {
    // identity 無し scene はバッジ非表示 (= 旧 free-text 経路で動く)
    return null;
  }
  if (enabled === false) {
    return (
      <span
        className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400"
        title="CLIP_LIBRARY_ENABLED=0 (= env var)。設計通り opt-in なので default OFF。設定すると hit 経路が動く"
      >
        💤 clip_library OFF
      </span>
    );
  }
  if (status.satisfied) {
    return (
      <span
        className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-700/40 text-emerald-200"
        title={`clip_library HIT (= AI 課金 0)\n entry_id: ${status.entry_id}\n pool_size: ${status.pool_size ?? "?"}`}
      >
        📦 clip lib HIT
      </span>
    );
  }
  return (
    <span
      className="text-[10px] px-1.5 py-0.5 rounded bg-amber-700/40 text-amber-200"
      title="identity あるが pool 空 → cold path で生成 (= AI 課金あり)。生成後に register されて 2 回目以降は HIT する"
    >
      ⚠️ clip lib MISS
    </span>
  );
}
