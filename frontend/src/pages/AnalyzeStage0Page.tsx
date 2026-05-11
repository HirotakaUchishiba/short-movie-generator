import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import AnalyzeJobView from "../components/AnalyzeJobView";
import { StageFailureAlert } from "../components/common/StageFailureAlert";
import { useDeleteProject } from "../hooks/useDeleteProject";
import type { ProjectDetail, StageErrorDetail } from "../types";

/**
 * `/project/<TS>/analyze` の page。
 *
 * from-reference-video 経路の主導フローで、Stage 0 (analyze pipeline) の
 * 進行状況を表示する。ProjectShell とは別 layout (= ProjectShell は
 * screenplay non-null 前提)。
 *
 * - analyze_status="running"/"pending": AnalyzeJobView を projectTs 付きで描画
 * - analyze_status="failed": FailedActions (retry / delete / TOP back) を描画
 * - analyze_status="completed" or null + screenplay あり: /project/<TS>/script に redirect
 */
export default function AnalyzeStage0Page() {
  const { ts } = useParams<{ ts: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // initial load + polling (= SSE 切断時の安全網。AnalyzeJobView の SSE が
  // 即時更新するので 5 秒間隔で十分)
  useEffect(() => {
    if (!ts) return;
    let stop = false;
    let timerId: number | null = null;

    const tick = async () => {
      if (stop) return;
      try {
        const d = await api.project(ts);
        if (stop) return;
        setDetail(d);
        // Stage 0 完了済 / legacy 経路 → Stage 1 page へ自動遷移
        if (
          d.analyze_status === "completed" ||
          (d.analyze_status == null && d.screenplay_name)
        ) {
          navigate(`/project/${ts}/script`, { replace: true });
          return;
        }
      } catch (e) {
        if (!stop) setError(String(e));
        return;
      }
      if (!stop) timerId = window.setTimeout(tick, 5000);
    };
    void tick();
    return () => {
      stop = true;
      if (timerId !== null) {
        window.clearTimeout(timerId);
        timerId = null;
      }
    };
  }, [ts, navigate]);

  if (!ts) return <div className="p-6">invalid project</div>;
  if (error) {
    return (
      <div className="container mx-auto p-6 max-w-3xl space-y-4">
        <div className="card border border-rose-500/40 text-rose-200">
          {error}
        </div>
        <Link to="/" className="btn-ghost inline-block">
          ← プロジェクト一覧
        </Link>
      </div>
    );
  }
  if (!detail) return <div className="p-6 text-slate-400">読み込み中...</div>;

  return (
    <div className="container mx-auto p-6 max-w-3xl space-y-4">
      <header className="flex items-center justify-between">
        <Link to="/" className="text-sm text-slate-400 hover:text-emerald-400">
          ← プロジェクト一覧
        </Link>
        <h1 className="text-lg font-semibold">
          📹 参考動画を分析中
          <span className="ml-3 text-xs text-slate-400 font-mono">{ts}</span>
        </h1>
      </header>

      {detail.analyze_status === "failed" && (
        <FailedActions
          ts={ts}
          errorDetail={detail.progress?.stages?.analyze?.error_detail ?? null}
        />
      )}
      {detail.analyze_status !== "failed" && detail.analyze_job_id && (
        <AnalyzeJobView jobId={detail.analyze_job_id} projectTs={ts} />
      )}
    </div>
  );
}

function FailedActions({
  ts,
  errorDetail,
}: {
  ts: string;
  errorDetail: StageErrorDetail | null;
}) {
  const navigate = useNavigate();
  const [retryBusy, setRetryBusy] = useState(false);
  const [retryErr, setRetryErr] = useState<string | null>(null);
  const {
    deleteProject,
    busy: deleteBusy,
    error: deleteErr,
  } = useDeleteProject({
    onSuccess: () => navigate("/", { replace: true }),
  });

  const busy = retryBusy || deleteBusy;
  const err = retryErr || deleteErr;

  // error_detail が無い旧 project の fallback envelope (= 設計 doc 後方互換)
  const fallbackDetail: StageErrorDetail = errorDetail ?? {
    type: "unknown",
    message: "原因情報が記録されていません (= 旧 progress.json)",
    actionable_hint:
      "再度リトライしてください。原因が再現する場合はサーバログを確認してください。",
  };

  return (
    <>
      <StageFailureAlert
        stageLabel="分析"
        errorDetail={fallbackDetail}
        retryHint="retry は cache (= frames / audio / whisper) が効くので追加課金は最小です。"
        onRetry={
          busy
            ? undefined
            : async () => {
                setRetryBusy(true);
                setRetryErr(null);
                try {
                  await api.retryAnalyzeForProject(ts);
                  window.location.reload();
                } catch (e) {
                  setRetryErr(String(e));
                } finally {
                  setRetryBusy(false);
                }
              }
        }
        onDelete={busy ? undefined : () => void deleteProject(ts)}
        onDismiss={busy ? undefined : () => navigate("/", { replace: true })}
        retryLabel="リトライ"
        deleteLabel="削除"
        dismissLabel="後で (TOP に戻る)"
      />
      {err && (
        <div className="card border border-rose-500/40 text-sm text-rose-200 whitespace-pre-wrap">
          {err}
        </div>
      )}
    </>
  );
}
