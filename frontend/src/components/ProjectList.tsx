import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { ProjectListItem } from "../types";

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
    <div className="max-w-5xl mx-auto p-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold mb-2">tensyoku movie generator</h1>
        <p className="text-slate-400 text-sm">
          段階的ゲート方式で動画を生成。各stageで人間が確認・承認してから次に進めます。
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-rose-700 bg-rose-900/40 p-3 text-sm">
          {error}
        </div>
      )}

      <section className="card mb-8">
        <h2 className="text-lg font-semibold mb-3">新規プロジェクト</h2>
        <div className="flex gap-3 items-center">
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
        <h2 className="text-lg font-semibold mb-3">既存プロジェクト</h2>
        {loading && <p className="text-slate-400">読み込み中...</p>}
        {!loading && projects.length === 0 && (
          <p className="text-slate-400">プロジェクトがありません</p>
        )}
        <ul className="space-y-2">
          {projects.map((p) => (
            <li key={p.timestamp}>
              <Link
                to={`/project/${p.timestamp}`}
                className="card flex justify-between items-center hover:border-emerald-400"
              >
                <div>
                  <div className="font-medium">{p.screenplay_name}</div>
                  <div className="text-xs text-slate-400">
                    {p.timestamp} · 作成 {p.created_at}
                  </div>
                </div>
                <div className="text-sm">
                  <span className="badge bg-slate-700 text-slate-200">
                    現在: {p.current_stage ?? "完了"}
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
