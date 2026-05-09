import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, bgAssetUrl } from "../api";
import type { ProjectListItem, StageName } from "../types";

const STAGE_LABELS: Record<StageName, string> = {
  script: "台本",
  tts: "TTS",
  bg: "背景",
  kling: "Kling",
  scene: "音声合成",
  overlay: "字幕",
  final_import: "取込",
  publish: "公開",
};

function formatCreatedAt(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const m = d.getMonth() + 1;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${m}/${day} ${hh}:${mm}`;
}

function ProjectCard({ p }: { p: ProjectListItem }) {
  const stageLabel = p.current_stage
    ? (STAGE_LABELS[p.current_stage] ?? p.current_stage)
    : "完了";
  const isDone = !p.current_stage;
  return (
    <Link
      to={`/project/${p.timestamp}`}
      className="group flex flex-col overflow-hidden rounded-lg border border-slate-700 bg-slate-800/50 transition hover:border-emerald-400 hover:bg-slate-800"
    >
      <div className="relative aspect-[9/16] overflow-hidden bg-slate-900">
        {p.has_bg_thumbnail ? (
          <img
            src={bgAssetUrl(p.timestamp, 0)}
            alt=""
            className="h-full w-full object-cover transition group-hover:scale-[1.02]"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center text-slate-600">
            <svg
              className="h-10 w-10"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3.75 6.75A2.25 2.25 0 016 4.5h12a2.25 2.25 0 012.25 2.25v10.5A2.25 2.25 0 0118 19.5H6a2.25 2.25 0 01-2.25-2.25V6.75z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9.75 10.5l3.75 4.5 2.25-2.625L19.5 16.5"
              />
            </svg>
            <span className="mt-2 text-xs">背景未生成</span>
          </div>
        )}
        <div className="absolute left-2 top-2">
          <span
            className={
              "badge " +
              (isDone
                ? "bg-emerald-600/90 text-white"
                : "bg-slate-900/80 text-slate-100 backdrop-blur")
            }
          >
            {isDone ? "✓ " : ""}
            {stageLabel}
          </span>
        </div>
        {p.scene_count > 0 && (
          <div className="absolute bottom-2 right-2">
            <span className="badge bg-slate-900/80 text-slate-200 backdrop-blur">
              {p.scene_count}シーン
            </span>
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div
          className="line-clamp-2 text-sm font-semibold leading-snug"
          title={p.display_title}
        >
          {p.display_title}
        </div>
        {p.caption_hashtags && (
          <div
            className="line-clamp-1 text-xs text-emerald-400/80"
            title={p.caption_hashtags}
          >
            {p.caption_hashtags}
          </div>
        )}
        <div className="mt-auto text-[11px] text-slate-500">
          {formatCreatedAt(p.created_at)}
        </div>
      </div>
    </Link>
  );
}

export default function ProjectList() {
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [screenplays, setScreenplays] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [selectedScreenplay, setSelectedScreenplay] = useState("");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const reload = async () => {
    setLoading(true);
    try {
      const r = await api.projects();
      setProjects(r.projects);
      setScreenplays(r.screenplays);
      if (r.screenplays.length && !selectedScreenplay) {
        setSelectedScreenplay(r.screenplays[0]);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
  }, []);

  const onCreate = async () => {
    if (!selectedScreenplay) return;
    setCreating(true);
    setError(null);
    try {
      const r = await api.createProject(selectedScreenplay);
      navigate(`/project/${r.timestamp}/script`);
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl p-8">
      <header className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="mb-2 text-3xl font-bold">short movie generator</h1>
          <p className="text-sm text-slate-400">
            段階的ゲート方式で動画を生成。各stageで人間が確認・承認してから次に進めます。
          </p>
          <PendingAnalyticsBadge />
        </div>
        <Link to="/analyze" className="btn-ghost whitespace-nowrap text-sm">
          参考動画から台本を生成 →
        </Link>
      </header>

      {error && (
        <div className="mb-4 rounded border border-rose-700 bg-rose-900/40 p-3 text-sm">
          {error}
        </div>
      )}

      <section className="card mb-8">
        <h2 className="mb-3 text-lg font-semibold">新規プロジェクト</h2>
        <div className="flex items-center gap-3">
          <select
            className="input flex-1"
            value={selectedScreenplay}
            onChange={(e) => setSelectedScreenplay(e.target.value)}
          >
            {screenplays.length === 0 && (
              <option value="">台本がありません</option>
            )}
            {screenplays.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            className="btn-primary"
            disabled={!selectedScreenplay || creating}
            onClick={onCreate}
          >
            {creating ? "作成中..." : "プロジェクト作成"}
          </button>
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">既存プロジェクト</h2>
          {!loading && projects.length > 0 && (
            <span className="text-xs text-slate-500">{projects.length}件</span>
          )}
        </div>
        {loading && <p className="text-slate-400">読み込み中...</p>}
        {!loading && projects.length === 0 && (
          <p className="text-slate-400">プロジェクトがありません</p>
        )}
        {!loading && projects.length > 0 && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {projects.map((p) => (
              <ProjectCard key={p.timestamp} p={p} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function PendingAnalyticsBadge() {
  const [count, setCount] = useState<number | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  const reload = async () => {
    try {
      const r = await api.analyticsPendingStatus();
      setCount(r.count);
    } catch {
      setCount(null);
    }
  };

  useEffect(() => {
    void reload();
    const t = window.setInterval(() => void reload(), 30_000);
    return () => window.clearInterval(t);
  }, []);

  if (count === null || count === 0) return null;

  const onSync = async () => {
    if (syncing) return;
    setSyncing(true);
    setLastResult(null);
    try {
      const r = await api.analyticsPendingSync();
      setLastResult(`同期完了: ${r.success} 件成功 / ${r.failed} 件失敗`);
      await reload();
    } catch (e) {
      setLastResult(`同期失敗: ${String(e)}`);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="mt-3 flex items-center gap-2 text-xs">
      <span className="rounded bg-amber-700/40 px-2 py-1 text-amber-100">
        analytics 同期保留 {count} 件
      </span>
      <button
        type="button"
        className="btn-ghost text-xs"
        disabled={syncing}
        onClick={onSync}
      >
        {syncing ? "同期中…" : "今すぐ同期"}
      </button>
      {lastResult && <span className="text-slate-400">{lastResult}</span>}
    </div>
  );
}
