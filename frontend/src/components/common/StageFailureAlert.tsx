/**
 * Stage / phase 失敗時に原因を表示する共通 Alert コンポーネント。
 *
 * backend が tmp-progress.json.stages.<stage>.error_detail に書く構造化
 * envelope を受け取り、type / actionable_hint / message / request_id /
 * retry コスト見積を一貫した見た目で表示する。
 *
 * 詳細は docs/plannings/2026-05-11_pipeline-failure-detail-ui.md
 */
import { useState } from "react";
import type { StageErrorDetail } from "../../types";

interface StageFailureAlertProps {
  // 失敗した stage の表示名 (= "分析" / "TTS" / "背景" 等の日本語ラベル)
  stageLabel: string;
  // 構造化 error envelope。null/undefined ならコンポーネント自体 render しない
  errorDetail: StageErrorDetail | null | undefined;
  // 「retry は cache が効くので追加課金最小」等の補足。stage ごとに違う
  retryHint?: string;
  // ボタン callbacks (= 任意。指定された分だけ render する)
  onRetry?: () => void;
  onDelete?: () => void;
  onDismiss?: () => void;
  // ボタンラベル上書き
  retryLabel?: string;
  deleteLabel?: string;
  dismissLabel?: string;
}

// type → 短いラベル + 色 (= Tailwind palette)
const TYPE_LABELS: Record<StageErrorDetail["type"], string> = {
  credit_exhausted: "クレジット切れ",
  rate_limit: "レート制限",
  auth_failure: "認証失敗",
  quota_exceeded: "クォータ超過",
  context_too_long: "入力サイズ超過",
  safety_filter: "safety filter",
  network_timeout: "ネットワーク",
  disk_full: "ディスク容量不足",
  unknown: "不明",
};

export function StageFailureAlert({
  stageLabel,
  errorDetail,
  retryHint,
  onRetry,
  onDelete,
  onDismiss,
  retryLabel = "リトライ",
  deleteLabel = "削除",
  dismissLabel = "後で",
}: StageFailureAlertProps) {
  const [open, setOpen] = useState(false);
  if (!errorDetail) return null;

  const typeLabel = TYPE_LABELS[errorDetail.type] ?? errorDetail.type;
  const hint = errorDetail.actionable_hint ?? "";
  const costEstimate = errorDetail.retry_cost_estimate_usd;

  return (
    <div
      className="rounded border border-rose-500/40 bg-rose-900/10 p-4 text-sm text-rose-100"
      role="alert"
      data-testid="stage-failure-alert"
    >
      <div className="font-semibold text-rose-300">
        ⚠️ {stageLabel} で失敗しました
        <span className="ml-2 inline-block rounded bg-rose-500/20 px-2 py-0.5 text-xs">
          {typeLabel}
        </span>
        {errorDetail.failed_phase && (
          <span className="ml-1 text-xs text-rose-300/80">
            ({errorDetail.failed_phase} phase)
          </span>
        )}
      </div>

      {hint && (
        <div className="mt-2 text-rose-100/90" data-testid="stage-failure-hint">
          {hint}
        </div>
      )}

      {retryHint && (
        <div className="mt-1 text-xs text-rose-200/70">{retryHint}</div>
      )}

      <details
        className="mt-3"
        open={open}
        onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary className="cursor-pointer text-xs text-rose-200/80 hover:text-rose-200">
          詳細を{open ? "閉じる" : "表示"}
        </summary>
        <div className="mt-2 space-y-1 rounded bg-rose-900/20 p-2 text-xs">
          {errorDetail.message && (
            <div>
              <span className="text-rose-300/80">message: </span>
              <span
                className="break-all whitespace-pre-wrap"
                data-testid="stage-failure-message"
              >
                {errorDetail.message}
              </span>
            </div>
          )}
          {errorDetail.request_id && (
            <div>
              <span className="text-rose-300/80">request_id: </span>
              <span className="font-mono">{errorDetail.request_id}</span>
            </div>
          )}
          {errorDetail.occurred_at && (
            <div>
              <span className="text-rose-300/80">発生時刻: </span>
              <span>{errorDetail.occurred_at}</span>
            </div>
          )}
          {typeof costEstimate === "number" && (
            <div>
              <span className="text-rose-300/80">retry コスト見積: </span>
              <span>${costEstimate.toFixed(2)} (履歴 median)</span>
            </div>
          )}
        </div>
      </details>

      {(onRetry || onDelete || onDismiss) && (
        <div className="mt-3 flex gap-2">
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500"
            >
              🔄 {retryLabel}
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              className="rounded bg-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-600"
            >
              🗑️ {deleteLabel}
            </button>
          )}
          {onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              className="rounded px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              {dismissLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
