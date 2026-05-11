/**
 * Project 削除の共通ロジック (= ProjectList card / AnalyzeStage0Page で共有)。
 *
 * 設計 doc: docs/plannings/2026-05-11_delete-projects-ui.md §3.4
 *
 * 共通化の目的:
 *   - 確認ダイアログ文言を 1 箇所に集約
 *   - busy / error state の見せ方を統一
 *   - 削除成功時の callback (= list refetch / navigate) を呼び元に委譲
 */
import { useState, useCallback } from "react";
import { api } from "../api";

interface UseDeleteProjectOptions {
  /** 削除成功後に呼ばれる。再 fetch や navigate を呼び元で実施する。 */
  onSuccess?: (ts: string) => void;
  /** 確認ダイアログをスキップする場合 (= 内部呼び出し / bulk delete 等)。既定 false。 */
  skipConfirm?: boolean;
  /** confirm dialog に出す project title (= 削除対象を明示)。省略時は ts のみ。 */
  titleHint?: string;
}

interface UseDeleteProjectReturn {
  deleteProject: (ts: string) => Promise<void>;
  busy: boolean;
  error: string | null;
  clearError: () => void;
}

const CONFIRM_MESSAGE_PREFIX = "プロジェクトを削除しますか?\n\n";
const CONFIRM_MESSAGE_BODY =
  "削除:\n" +
  "  • temp/<TS>/ ディレクトリ (= 台本 / 進捗 / 中間ファイル)\n" +
  "  • 分析実行中の場合はジョブを中止\n\n" +
  "残す:\n" +
  "  • 参考動画 (= 他プロジェクトと共有)\n" +
  "  • 分析履歴 / 投稿履歴 (= analytics DB)";

export function useDeleteProject({
  onSuccess,
  skipConfirm = false,
  titleHint,
}: UseDeleteProjectOptions = {}): UseDeleteProjectReturn {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const deleteProject = useCallback(
    async (ts: string) => {
      if (!skipConfirm) {
        const header = titleHint
          ? `プロジェクト「${titleHint}」(${ts}) を削除しますか?\n\n`
          : `プロジェクト ${ts} を削除しますか?\n\n`;
        if (!window.confirm(header + CONFIRM_MESSAGE_BODY)) {
          return;
        }
      }
      setBusy(true);
      setError(null);
      try {
        await api.deleteProject(ts);
        onSuccess?.(ts);
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
      }
    },
    [onSuccess, skipConfirm, titleHint],
  );

  const clearError = useCallback(() => setError(null), []);

  return { deleteProject, busy, error, clearError };
}

// confirm 文言を component test から検証するため export する
export const CONFIRM_HINTS = {
  PREFIX: CONFIRM_MESSAGE_PREFIX,
  BODY: CONFIRM_MESSAGE_BODY,
};
