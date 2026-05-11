/**
 * ProjectCard 上に置く小さな削除ボタン。
 *
 * 設計 doc: docs/plannings/2026-05-11_delete-projects-ui.md §3.2
 *
 * - mode="icon": 🗑 だけのコンパクト表示 (= card hover で出る)
 * - mode="label": "🗑 削除" ラベル付き (= 失敗 card で常時表示)
 *
 * 親 (= Link の中) で誤って遷移しないよう、click は preventDefault +
 * stopPropagation を呼ぶ。
 */
import type { MouseEvent } from "react";

import { useDeleteProject } from "../../hooks/useDeleteProject";

interface DeleteProjectButtonProps {
  ts: string;
  /** 確認 dialog に出す project title (= optional だが UX 上推奨)。 */
  titleHint?: string;
  /** 削除成功時に呼ばれる (= 一覧 refetch / navigate を呼び元が実施)。 */
  onDeleted: (ts: string) => void;
  mode?: "icon" | "label";
  /** 追加 className (= 位置調整、background など)。 */
  className?: string;
}

export function DeleteProjectButton({
  ts,
  titleHint,
  onDeleted,
  mode = "icon",
  className = "",
}: DeleteProjectButtonProps) {
  const { deleteProject, busy, error } = useDeleteProject({
    onSuccess: onDeleted,
    titleHint,
  });

  const handleClick = async (e: MouseEvent<HTMLButtonElement>) => {
    // Link の中に居る場合は親 anchor の遷移を抑制する
    e.preventDefault();
    e.stopPropagation();
    await deleteProject(ts);
  };

  const base =
    mode === "icon"
      ? "rounded-full bg-slate-900/80 px-2 py-1 text-sm text-slate-200 hover:bg-rose-700 hover:text-white"
      : "rounded bg-rose-600/90 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-500";

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={busy}
      aria-label={`プロジェクト ${ts} を削除`}
      title={
        error ? `削除失敗: ${error}` : busy ? "削除中..." : "プロジェクトを削除"
      }
      className={`${base} disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
    >
      {busy ? "..." : mode === "icon" ? "🗑" : "🗑 削除"}
    </button>
  );
}
