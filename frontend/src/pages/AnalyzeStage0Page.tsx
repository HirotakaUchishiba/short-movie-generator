import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import AnalyzeJobView from "../components/AnalyzeJobView";
import type { ProjectDetail } from "../types";

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

      {detail.analyze_status === "failed" && <FailedActions ts={ts} />}
      {detail.analyze_status !== "failed" && detail.analyze_job_id && (
        <AnalyzeJobView jobId={detail.analyze_job_id} projectTs={ts} />
      )}
    </div>
  );
}

function FailedActions({ ts }: { ts: string }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  return (
    <div className="card border border-rose-500/40">
      <h3 className="font-semibold text-rose-300 mb-2">⚠ 分析が失敗しました</h3>
      <p className="text-sm text-slate-300 mb-3">
        以下から選んでください。retry は cache (= frames / audio / whisper)
        が効くので追加課金は最小です。
      </p>
      {err && (
        <div className="mb-3 text-sm text-rose-300 whitespace-pre-wrap">
          {err}
        </div>
      )}
      <div className="flex gap-2 flex-wrap">
        <button
          className="btn-primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setErr(null);
            try {
              await api.retryAnalyzeForProject(ts);
              window.location.reload();
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          🔁 リトライ
        </button>
        <button
          className="btn-ghost"
          disabled={busy}
          onClick={async () => {
            if (!window.confirm("このプロジェクトを削除しますか?")) return;
            setBusy(true);
            setErr(null);
            try {
              await api.deleteProject(ts);
              window.location.href = "/";
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          🗑 削除
        </button>
        <Link to="/" className="btn-ghost">
          後で (TOP に戻る)
        </Link>
      </div>
    </div>
  );
}
