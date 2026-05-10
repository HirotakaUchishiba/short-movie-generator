import { useEffect, useState, useCallback } from "react";
import {
  Outlet,
  useParams,
  Link,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { api } from "../api";
import type {
  ProjectDetail,
  Screenplay,
  StageName,
  ServerConfig,
  JobStatus,
} from "../types";
import StageProgressBar from "./StageProgressBar";

// Stage 1+ child component に渡る context は **screenplay と screenplay_name が
// non-null 確定** の状態。Stage 0 中 (= analyze pending) の project は
// AnalyzeStage0Page (= /project/<TS>/analyze) が描画する別 layout なので
// ProjectShell には到達しない (= Phase B Commit 4 で redirect 実装)。
type LoadedProjectDetail = ProjectDetail & {
  screenplay: Screenplay;
  screenplay_name: string;
};

interface Ctx {
  detail: LoadedProjectDetail;
  serverConfig: ServerConfig;
  reload: () => Promise<void>;
  reloadConfig: () => Promise<void>;
  approveCurrent: (stage: StageName) => Promise<void>;
  runNext: () => Promise<void>;
  regen: (body: {
    stage: StageName;
    scene_idx?: number;
    line_idx?: number;
    force?: boolean;
  }) => Promise<void>;
  jobStatus: JobStatus | null;
}

export default function ProjectShell() {
  const { ts } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [serverConfig, setServerConfig] = useState<ServerConfig | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!ts) return;
    try {
      const r = await api.project(ts);
      setDetail(r);
    } catch (e) {
      setError(String(e));
    }
  }, [ts]);

  const reloadConfig = useCallback(async () => {
    try {
      const c = await api.config();
      setServerConfig(c);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    reloadConfig();
  }, [reloadConfig]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Stage 0 中の project は専用 page (= /project/<TS>/analyze) に redirect。
  // detail を fetch した後で判定する (= analyze_status は Phase A backend が
  // api_project_detail に乗せている)。
  useEffect(() => {
    if (!ts || !detail) return;
    const s = detail.analyze_status;
    if (s === "running" || s === "pending" || s === "failed") {
      navigate(`/project/${ts}/analyze`, { replace: true });
    }
  }, [ts, detail, navigate]);

  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    let timerId: number | null = null;
    const tick = async () => {
      if (stop) return;
      try {
        const j = await api.job(jobId);
        if (stop) return;
        setJobStatus(j);
        if (j.status === "completed" || j.status === "failed") {
          await reload();
          if (stop) return;
          if (j.status === "failed") setError(j.error ?? "ジョブ失敗");
          if (j.status === "completed") setJobId(null);
          return;
        }
      } catch (e) {
        if (!stop) setError(String(e));
        return;
      }
      if (!stop) timerId = window.setTimeout(tick, 1500);
    };
    void tick();
    return () => {
      stop = true;
      if (timerId !== null) {
        window.clearTimeout(timerId);
        timerId = null;
      }
    };
  }, [jobId, reload]);

  const approveCurrent = async (stage: StageName) => {
    if (!ts) return;
    setError(null);
    try {
      const r = await api.approve(ts, stage);
      await reload();
      if (r.next_stage) {
        const job = await api.runNext(ts);
        setJobId(job.job_id);
        navigate(`/project/${ts}/${r.next_stage}`);
      }
    } catch (e) {
      setError(String(e));
    }
  };

  const runNext = async () => {
    if (!ts) return;
    setError(null);
    try {
      const job = await api.runNext(ts);
      setJobId(job.job_id);
    } catch (e) {
      setError(String(e));
    }
  };

  const regen = async (body: {
    stage: StageName;
    scene_idx?: number;
    line_idx?: number;
    force?: boolean;
  }) => {
    if (!ts) return;
    setError(null);
    try {
      const job = await api.regen(ts, body);
      setJobId(job.job_id);
    } catch (e) {
      setError(String(e));
    }
  };

  if (!detail || !serverConfig) {
    return <div className="p-8 text-slate-400">読み込み中...</div>;
  }
  if (!detail.screenplay || !detail.screenplay_name) {
    // Stage 0 中の project が誤って ProjectShell に流れ込んだケース
    // (= Phase B Commit 4 で /project/<TS>/analyze に redirect する)。
    return (
      <div className="p-8 text-slate-400">プロジェクトを読み込み中...</div>
    );
  }

  const loadedDetail = detail as LoadedProjectDetail;
  const ctx: Ctx = {
    detail: loadedDetail,
    serverConfig,
    reload,
    reloadConfig,
    approveCurrent,
    runNext,
    regen,
    jobStatus,
  };

  const currentStageInPath = location.pathname.split("/").pop() as StageName;

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-700 bg-slate-800/60 px-6 py-3">
        <div className="flex items-center justify-between">
          <div>
            <Link
              to="/"
              className="text-sm text-slate-400 hover:text-emerald-400"
            >
              ← プロジェクト一覧
            </Link>
            <h1 className="text-lg font-semibold mt-1">
              {loadedDetail.screenplay_name}
              <span className="ml-3 text-xs text-slate-400">
                {loadedDetail.timestamp}
              </span>
            </h1>
          </div>
          {jobStatus && jobStatus.status === "running" && (
            <div className="badge bg-amber-500/20 text-amber-300">
              ジョブ実行中: {jobStatus.kind} ({jobStatus.elapsed}s)
            </div>
          )}
        </div>
        <StageProgressBar
          progress={detail.progress}
          currentInPath={currentStageInPath}
          ts={detail.timestamp}
        />
      </header>

      {error && (
        <div className="mx-6 my-3 rounded border border-rose-700 bg-rose-900/40 p-3 text-sm">
          <div className="flex justify-between">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-rose-300">
              ✕
            </button>
          </div>
        </div>
      )}

      <main className="flex-1 p-6 overflow-x-hidden">
        <Outlet context={ctx} />
      </main>
    </div>
  );
}
