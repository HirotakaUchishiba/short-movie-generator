import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  formatDuration,
  PHASE_HINTS,
  PHASE_LABELS,
  PHASE_ORDER,
  STATUS_LABELS,
} from "./analyze-job-utils";
import { useAnalyzeJob } from "../hooks/useAnalyzeJob";

// PhaseState / AnnotationStats / SuggestedIntent は ../hooks/useAnalyzeJob.ts に
// 移管済 (= §3.3 巨大関数分解)。

interface Props {
  jobId: string;
  /** Stage 0 page (= /project/<TS>/analyze) が渡す project の TS。完了時に
   * `/project/<TS>/script` へ自動遷移する。 */
  projectTs: string;
}

export default function AnalyzeJobView({ jobId, projectTs }: Props) {
  const {
    job,
    phases,
    now,
    dryrun,
    completedPath,
    error,
    confirmBusy,
    claudeChars,
    annotationStats,
    suggestedIntents,
    isTerminal,
    completedCount,
    totalCount,
    overallPct,
    jobStartedAt,
    jobFinishedAt,
    overallElapsedMs,
    currentPhase,
    currentPhaseElapsedMs,
    confirmCostGate,
    cancelJob,
  } = useAnalyzeJob(jobId);

  if (!job) return <div className="text-sm text-slate-400">読み込み中...</div>;

  const screenplayName = completedPath
    ? completedPath
        .split("/")
        .pop()
        ?.replace(/\.json$/, "")
    : null;

  // プログレスバーの色
  const barColor =
    job.status === "failed"
      ? "bg-rose-500"
      : job.status === "cancelled"
        ? "bg-slate-500"
        : job.status === "completed"
          ? "bg-emerald-500"
          : "bg-emerald-600";

  const showCurrentPhasePanel =
    currentPhase && (job.status === "running" || job.status === "dryrunning");

  return (
    <div className="space-y-4">
      {/* ─── ヘッダー (ID + status + キャンセル) ──────────── */}
      <div className="card">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-400 font-mono">{job.id}</div>
            <div className="text-sm">
              status:{" "}
              <span className="font-mono">{STATUS_LABELS[job.status]}</span>
            </div>
          </div>
          {!isTerminal && (
            <button
              className="btn-ghost text-xs"
              onClick={() => {
                if (!confirm("ジョブをキャンセルしますか?")) return;
                void cancelJob();
              }}
            >
              キャンセル
            </button>
          )}
        </div>
        {error && (
          <div className="mt-2 text-sm text-rose-300 whitespace-pre-wrap">
            error: {error}
          </div>
        )}
      </div>

      {/* ─── 全体プログレスバー ─────────────────────────── */}
      <div className="card">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold">全体進捗</h3>
          <div className="text-xs text-slate-400 font-mono">
            {jobStartedAt
              ? `経過 ${formatDuration(overallElapsedMs)}`
              : "未開始"}
          </div>
        </div>
        <div className="h-3 w-full rounded bg-slate-700 overflow-hidden">
          <div
            className={`h-full ${barColor} transition-all duration-300`}
            style={{ width: `${overallPct}%` }}
          />
        </div>
        <div className="mt-1 text-xs text-slate-400 flex justify-between">
          <span>
            {completedCount} / {totalCount} フェーズ完了
          </span>
          <span className="font-mono">{Math.round(overallPct)}%</span>
        </div>
      </div>

      {/* ─── 現在実行中フェーズ強調 ────────────────────── */}
      {showCurrentPhasePanel && currentPhase && (
        <div className="card border border-amber-500/40 bg-amber-900/10">
          <div className="text-xs text-amber-400 mb-1">⏱ 現在実行中</div>
          <div className="flex items-start gap-3">
            <div className="text-amber-300 text-2xl animate-pulse leading-none">
              ▶
            </div>
            <div className="flex-1">
              <div className="text-base font-semibold text-amber-100">
                {PHASE_LABELS[currentPhase]}
              </div>
              <div className="text-xs text-slate-400 mt-1">
                {PHASE_HINTS[currentPhase]}
              </div>
              <div className="text-xs text-slate-400 mt-2 font-mono">
                このフェーズ: {formatDuration(currentPhaseElapsedMs)}
              </div>
              {currentPhase === "claude" && claudeChars > 0 && (
                <div className="text-xs text-emerald-300 mt-1">
                  Claude が生成中... ({claudeChars.toLocaleString()} 文字)
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ─── フェーズ詳細 (タイムライン) ────────────────── */}
      <div className="card">
        <h3 className="font-semibold mb-2">フェーズ詳細</h3>
        <ol className="space-y-1 text-sm">
          {PHASE_ORDER.map((p) => {
            const st = phases[p];
            const isCurrent = currentPhase === p && !isTerminal;
            const color =
              st.status === "completed"
                ? "text-emerald-300"
                : st.status === "running"
                  ? "text-amber-300"
                  : st.status === "failed"
                    ? "text-rose-300"
                    : st.status === "skipped"
                      ? "text-slate-500"
                      : "text-slate-400";
            const icon =
              st.status === "completed"
                ? "✓"
                : st.status === "running"
                  ? "▶"
                  : st.status === "failed"
                    ? "✗"
                    : st.status === "skipped"
                      ? "—"
                      : "·";
            return (
              <li
                key={p}
                className={`${color} ${isCurrent ? "font-semibold" : ""}`}
              >
                <span className="font-mono mr-2">{icon}</span>
                {PHASE_LABELS[p]}
                {st.fromCache && (
                  <span className="ml-2 text-xs text-slate-500">(cache)</span>
                )}
                {st.durationMs != null && (
                  <span className="ml-2 text-xs text-slate-500 font-mono">
                    {(st.durationMs / 1000).toFixed(2)}s
                  </span>
                )}
                {isCurrent && (
                  <span className="ml-2 text-xs text-amber-400 font-mono">
                    {formatDuration(currentPhaseElapsedMs)}
                  </span>
                )}
                {st.message && (
                  <span className="ml-2 text-xs text-slate-500">
                    {st.message}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      {/* ─── コストゲート モーダル ──────────────────────── */}
      {dryrun && job.status === "awaiting_confirm" && (
        <div className="card border border-amber-500/40">
          <h3 className="font-semibold mb-2 text-amber-300">
            ⚠ Claude 呼び出しの確認
          </h3>
          <div className="text-sm space-y-1">
            <div>
              フレーム数:{" "}
              <span className="font-mono">{dryrun.frame_count}</span>
            </div>
            <div>
              推定 input tokens:{" "}
              <span className="font-mono">
                {dryrun.input_tokens?.toLocaleString()}
              </span>
            </div>
            <div>
              推定 output tokens:{" "}
              <span className="font-mono">
                {dryrun.output_tokens?.toLocaleString()}
              </span>
            </div>
            <div>
              推定コスト:{" "}
              <span className="font-mono text-amber-300">
                {dryrun.cost_usd == null
                  ? "履歴不足"
                  : `$${dryrun.cost_usd.toFixed(3)}`}
              </span>
              {dryrun.cost_jpy != null && (
                <span className="ml-2 text-xs text-slate-400">
                  (≈ ¥{Math.round(dryrun.cost_jpy)})
                </span>
              )}
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <button
              className="btn-primary"
              onClick={() => void confirmCostGate()}
              disabled={confirmBusy}
            >
              {confirmBusy ? "..." : "Claude 呼び出しを許可"}
            </button>
            <button
              className="btn-ghost"
              onClick={() => {
                if (!confirm("ジョブをキャンセルしますか?")) return;
                void cancelJob();
              }}
            >
              キャンセル
            </button>
          </div>
        </div>
      )}

      {/* ─── 完了時のサマリ + リンク ────────────────────── */}
      {completedPath && screenplayName && (
        <div className="card border border-emerald-500/40">
          <h3 className="font-semibold mb-2 text-emerald-300">
            ✓ 台本作成完了
          </h3>
          <div className="text-sm">
            台本: <span className="font-mono break-all">{completedPath}</span>
          </div>
          {jobStartedAt && jobFinishedAt && (
            <div className="text-xs text-slate-400 mt-1">
              総所要時間: {formatDuration(jobFinishedAt - jobStartedAt)}
            </div>
          )}
          {annotationStats && (
            <div
              className="text-xs text-slate-300 mt-2"
              data-testid="annotation-stats"
            >
              annotation:{" "}
              <span className="font-mono text-emerald-300">
                {annotationStats.with_visual_intent_id}
              </span>{" "}
              hit / {annotationStats.total_scenes} scenes
              {Object.keys(annotationStats.by_intent_id).length > 0 && (
                <span className="ml-1 text-slate-400">
                  (
                  {Object.entries(annotationStats.by_intent_id)
                    .map(([id, n]) => `${id}: ${n}`)
                    .join(", ")}
                  {annotationStats.low_confidence_demoted > 0 &&
                    `, low conf demoted: ${annotationStats.low_confidence_demoted}`}
                  )
                </span>
              )}
              {Object.keys(annotationStats.by_intent_id).length === 0 &&
                annotationStats.low_confidence_demoted > 0 && (
                  <span className="ml-1 text-slate-400">
                    (low conf demoted: {annotationStats.low_confidence_demoted})
                  </span>
                )}
            </div>
          )}
          {suggestedIntents.length > 0 && (
            <div
              className="mt-2 text-xs text-amber-200"
              data-testid="suggested-intents"
            >
              <Link
                to="/intent-catalog#suggestions"
                className="text-amber-300 hover:text-amber-100 underline"
              >
                💡 新規 intent 候補 {suggestedIntents.length} 件
              </Link>
              <span className="ml-2 text-slate-400">
                (= 連続して既存 catalog にマッチしないシーンが見つかりました。
                IntentCatalog の「💡 提案」セクションでトリアージしてください)
              </span>
            </div>
          )}
          <AutoNavigateOnComplete ts={projectTs} />
        </div>
      )}
    </div>
  );
}

function AutoNavigateOnComplete({ ts }: { ts: string }) {
  const navigate = useNavigate();
  useEffect(() => {
    // backend save-phase hook (= snapshot copy + Stage 1 unlock) が
    // 完了するまでのマージン。ユーザーが「完了」を視認できる時間も兼ねる。
    const t = window.setTimeout(() => {
      navigate(`/project/${ts}/script`);
    }, 1500);
    return () => window.clearTimeout(t);
  }, [navigate, ts]);
  return (
    <div className="mt-3 text-xs text-slate-400">
      Stage 1 (台本編集) に自動遷移します...
    </div>
  );
}
