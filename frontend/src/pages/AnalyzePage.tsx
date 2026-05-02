import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { AnalyzeJob, AnalyzeOptions, ReferenceVideo } from "../types";
import AnalyzeJobView from "../components/AnalyzeJobView";

const ALLOWED_EXTS = [".mov", ".mp4", ".webm", ".mkv"];

export default function AnalyzePage() {
  const [videos, setVideos] = useState<ReferenceVideo[]>([]);
  const [jobs, setJobs] = useState<AnalyzeJob[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [options, setOptions] = useState<AnalyzeOptions>({
    fps: 2.0,
  });
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [v, j] = await Promise.all([
        api.listReferenceVideos(),
        api.listAnalyzeJobs(),
      ]);
      setVideos(v.reference_videos);
      setJobs(j.jobs);
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const onFileSelected = async (file: File) => {
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED_EXTS.includes(ext)) {
      setError(
        `許可されていない拡張子: ${ext} (許可: ${ALLOWED_EXTS.join(", ")})`,
      );
      return;
    }
    setError(null);
    setUploading(true);
    setUploadPct(0);
    try {
      const r = await api.uploadReferenceVideo(file, (p) => setUploadPct(p));
      await refresh();
      setSelected(r.sha256);
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
      setUploadPct(0);
    }
  };

  const onStart = async () => {
    if (!selected) return;
    setCreating(true);
    setError(null);
    try {
      const r = await api.createAnalyzeJob(selected, options);
      setActiveJobId(r.job_id);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  };

  const onDeleteVideo = async (sha: string) => {
    if (!confirm("この動画を削除しますか?")) return;
    const finishDelete = async (force: boolean) => {
      await api.deleteReferenceVideo(sha, force);
      if (selected === sha) setSelected(null);
      await refresh();
    };
    try {
      await finishDelete(false);
    } catch (e) {
      const msg = String(e);
      if (msg.includes("409")) {
        const m = msg.match(/(\d+)\s*件/);
        const n = m ? m[1] : "?";
        const ok = confirm(
          `この動画は ${n} 件の分析ジョブから参照されています。\n` +
            `関連ジョブも一緒に削除しますか? (ジョブ履歴とフェーズ記録も消えます)`,
        );
        if (!ok) return;
        try {
          await finishDelete(true);
        } catch (e2) {
          setError(String(e2));
        }
        return;
      }
      setError(msg);
    }
  };

  return (
    <div className="container mx-auto p-6 max-w-5xl space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">参考動画から台本を生成</h1>
        <Link to="/" className="btn-ghost text-sm">
          プロジェクト一覧へ
        </Link>
      </header>

      {error && (
        <div className="card border border-rose-500/40 text-rose-200 text-sm whitespace-pre-wrap">
          {error}
        </div>
      )}

      {!activeJobId && (
        <>
          <section className="card">
            <h2 className="font-semibold mb-3">1. 動画アップロード</h2>
            <input
              type="file"
              accept={ALLOWED_EXTS.join(",")}
              disabled={uploading}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onFileSelected(f);
              }}
              className="text-sm"
            />
            {uploading && (
              <div className="mt-2">
                <div className="h-2 w-full rounded bg-slate-700 overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 transition-all"
                    style={{ width: `${Math.round(uploadPct * 100)}%` }}
                  />
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  アップロード中 {Math.round(uploadPct * 100)}%
                </div>
              </div>
            )}
            <div className="text-xs text-slate-500 mt-2">
              対応拡張子: {ALLOWED_EXTS.join(", ")} / 上限 1GB / 同一動画は
              dedup
            </div>
          </section>

          <section className="card">
            <h2 className="font-semibold mb-3">
              2. 動画を選択 ({videos.length}件)
            </h2>
            {videos.length === 0 ? (
              <div className="text-sm text-slate-400">
                まだ動画が登録されていません
              </div>
            ) : (
              <ul className="space-y-2">
                {videos.map((v) => {
                  const isSel = selected === v.sha256;
                  return (
                    <li
                      key={v.sha256}
                      className={`p-2 rounded border cursor-pointer transition ${
                        isSel
                          ? "border-emerald-500 bg-emerald-900/20"
                          : "border-slate-700 hover:border-slate-500"
                      }`}
                      onClick={() => setSelected(v.sha256)}
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="text-sm">{v.original_name}</div>
                          <div className="text-xs text-slate-400">
                            {(v.size_bytes / 1024 / 1024).toFixed(1)} MB
                            {v.duration_sec != null &&
                              ` · ${v.duration_sec.toFixed(1)}s`}
                            {" · "}
                            <span className="font-mono">
                              {v.sha256.slice(0, 12)}
                            </span>
                          </div>
                        </div>
                        <button
                          className="btn-ghost text-xs"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteVideo(v.sha256);
                          }}
                        >
                          削除
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {selected && (
            <section className="card">
              <h2 className="font-semibold mb-3">3. オプション</h2>
              <div className="space-y-3 text-sm">
                <div className="space-y-1">
                  <label className="flex items-center gap-3">
                    <span className="w-40">フレーム抽出間隔</span>
                    <input
                      type="number"
                      step="0.1"
                      min="0.1"
                      max="5.0"
                      value={(1 / (options.fps ?? 2.0)).toFixed(2)}
                      onChange={(e) => {
                        const sec = parseFloat(e.target.value);
                        if (!isNaN(sec) && sec >= 0.1) {
                          setOptions({
                            ...options,
                            fps: parseFloat((1 / sec).toFixed(3)),
                          });
                        }
                      }}
                      className="bg-slate-800 px-2 py-1 rounded w-20"
                    />
                    <span className="text-sm">秒ごとに 1 フレーム</span>
                    <span className="text-xs text-slate-500 font-mono">
                      (= fps {(options.fps ?? 2.0).toFixed(2)})
                    </span>
                  </label>
                  <div className="text-xs text-slate-400 pl-44">
                    既定 0.5 秒間隔。短いほど分析精度↑、Claude API への課金
                    (実費) も増加します。
                    <br />
                    目安: 60 秒の動画を既定値で分析すると ¥250〜400 程度
                    (実行前にコストゲートで推定額を確認できます)。
                  </div>
                </div>

                <label className="flex items-start gap-3">
                  <span className="w-32 mt-1">追加指示 (任意)</span>
                  <textarea
                    rows={2}
                    placeholder="例: TikTok UI は無視"
                    value={options.instructions ?? ""}
                    onChange={(e) =>
                      setOptions({
                        ...options,
                        instructions: e.target.value || null,
                      })
                    }
                    className="bg-slate-800 px-2 py-1 rounded flex-1"
                  />
                </label>
              </div>

              <div className="mt-4">
                <button
                  className="btn-primary"
                  onClick={onStart}
                  disabled={creating}
                >
                  {creating ? "起動中..." : "分析を開始"}
                </button>
              </div>
            </section>
          )}
        </>
      )}

      {activeJobId && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">分析ジョブ</h2>
            <button
              className="btn-ghost text-xs"
              onClick={() => {
                setActiveJobId(null);
                refresh();
              }}
            >
              ← 戻る
            </button>
          </div>
          <AnalyzeJobView jobId={activeJobId} />
        </section>
      )}

      {!activeJobId && jobs.length > 0 && (
        <section className="card">
          <h2 className="font-semibold mb-3">過去のジョブ ({jobs.length}件)</h2>
          <ul className="space-y-1 text-sm">
            {jobs.slice(0, 20).map((j) => (
              <li
                key={j.id}
                className="cursor-pointer hover:bg-slate-800 px-2 py-1 rounded"
                onClick={() => setActiveJobId(j.id)}
              >
                <span className="font-mono text-xs text-slate-500">{j.id}</span>
                <span className="ml-3">{j.status}</span>
                {j.estimated_cost_usd != null && (
                  <span className="ml-3 text-xs text-slate-400">
                    ${j.estimated_cost_usd.toFixed(3)}
                  </span>
                )}
                {j.created_at && (
                  <span className="ml-3 text-xs text-slate-500">
                    {j.created_at}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
