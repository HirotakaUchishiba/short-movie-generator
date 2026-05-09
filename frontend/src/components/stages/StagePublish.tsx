import { useCallback, useEffect, useRef, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api, finalVersionAssetUrl } from "../../api";
import type { FinalVersion, PublishedPost } from "../../types";

type Platform = "youtube" | "instagram" | "tiktok";
type Privacy = "private" | "unlisted" | "public";

const PLATFORM_LABELS: Record<Platform, string> = {
  youtube: "YouTube Shorts",
  instagram: "Instagram Reels",
  tiktok: "TikTok",
};

export default function StagePublish() {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const stage8Approved = !!ctx.detail.progress.stages.final_import?.approved_at;

  const [history, setHistory] = useState<PublishedPost[]>([]);
  const [canonical, setCanonical] = useState<FinalVersion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyPlatform, setBusyPlatform] = useState<Platform | null>(null);
  const [privacy, setPrivacy] = useState<Privacy>("private");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const reload = useCallback(async () => {
    try {
      const [{ published_posts }, { final_versions }] = await Promise.all([
        api.publishHistory(ts),
        api.listFinals(ts),
      ]);
      setHistory(published_posts);
      setCanonical(final_versions.find((v) => v.is_canonical) || null);
    } catch (e) {
      setError(String(e));
    }
  }, [ts]);

  useEffect(() => {
    reload();
  }, [reload]);

  const doPublish = async (platform: Platform) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;
    setError(null);
    setBusyPlatform(platform);
    try {
      const job = await api.publish(ts, {
        platform,
        privacy: platform === "youtube" ? privacy : undefined,
      });
      if (signal.aborted) return;
      // job ステータスをポーリング
      while (true) {
        await new Promise<void>((resolve, reject) => {
          const t = window.setTimeout(resolve, 1500);
          signal.addEventListener(
            "abort",
            () => {
              window.clearTimeout(t);
              reject(new DOMException("aborted", "AbortError"));
            },
            { once: true },
          );
        });
        if (signal.aborted) return;
        const j = await api.job(job.job_id);
        if (signal.aborted) return;
        if (j.status === "completed") break;
        if (j.status === "failed") {
          throw new Error(j.error || "publish failed");
        }
      }
      await reload();
      if (signal.aborted) return;
      await ctx.reload();
    } catch (e) {
      if (signal.aborted) return;
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError(String(e));
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
      if (!signal.aborted) {
        setBusyPlatform(null);
      }
    }
  };

  return (
    <StageGate
      stage="publish"
      title="プラットフォームへ公開"
      description="canonical な final 動画を YouTube / Instagram / TikTok に投稿し、analytics DB に登録する。YouTube は完全自動、IG / TikTok は半自動 (caption をクリップボードへ + アプリ起動)。"
    >
      {!stage8Approved ? (
        <div className="card text-center text-slate-400">
          まず 取込 を承認してください。
        </div>
      ) : !canonical ? (
        <div className="card text-center text-slate-400">
          canonical な final がありません。取込 タブで取り込んでください。
        </div>
      ) : (
        <>
          <div className="card mb-4">
            <h3 className="text-lg font-semibold mb-2">公開対象</h3>
            <div className="aspect-[9/16] bg-slate-950 overflow-hidden rounded mx-auto max-w-xs">
              <video
                src={finalVersionAssetUrl(ts, canonical.filename)}
                controls
                playsInline
                className="w-full h-full"
              />
            </div>
            <p className="text-xs text-slate-400 text-center mt-2">
              {canonical.filename} ·{" "}
              {(canonical.size_bytes / 1024 / 1024).toFixed(1)} MB
            </p>
          </div>

          {error && (
            <div className="rounded border border-rose-700 bg-rose-900/40 p-3 text-sm mb-4">
              <div className="flex justify-between">
                <span>{error}</span>
                <button onClick={() => setError(null)}>✕</button>
              </div>
            </div>
          )}

          <div className="card mb-4">
            <h3 className="text-lg font-semibold mb-3">公開アクション</h3>
            <div className="mb-3 text-sm">
              <label className="mr-2">YouTube 公開範囲:</label>
              <select
                value={privacy}
                onChange={(e) => setPrivacy(e.target.value as Privacy)}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1"
              >
                <option value="private">private (テスト)</option>
                <option value="unlisted">unlisted (限定公開)</option>
                <option value="public">public (公開)</option>
              </select>
            </div>
            <div className="flex flex-wrap gap-3">
              {(Object.keys(PLATFORM_LABELS) as Platform[]).map((p) => (
                <button
                  key={p}
                  className="btn-primary"
                  disabled={busyPlatform !== null}
                  onClick={() => doPublish(p)}
                >
                  {busyPlatform === p
                    ? "公開中..."
                    : `${PLATFORM_LABELS[p]} へ公開`}
                </button>
              ))}
            </div>
            <p className="text-xs text-slate-400 mt-3">
              IG / TikTok は半自動 — caption
              がクリップボードにコピーされ、対象アプリが開きます。
              アプリ側でアップロード完了後、URL を `register_post.py`
              で投入してください。
            </p>
          </div>

          {history.length > 0 && (
            <div className="card">
              <h3 className="text-lg font-semibold mb-2">公開履歴</h3>
              <table className="w-full text-sm">
                <thead className="text-slate-400 border-b border-slate-700">
                  <tr>
                    <th className="text-left py-2">platform</th>
                    <th className="text-left">video_id</th>
                    <th className="text-left">URL</th>
                    <th className="text-center">mode</th>
                    <th className="text-left">時刻</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((p) => (
                    <tr key={`${p.platform}-${p.published_at}`}>
                      <td className="py-2">{p.platform}</td>
                      <td>{p.video_id || "—"}</td>
                      <td>
                        {p.url ? (
                          <a
                            href={p.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-emerald-400 underline"
                          >
                            開く
                          </a>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="text-center text-xs">
                        {p.manual ? "手動" : "自動"}
                      </td>
                      <td>{p.published_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </StageGate>
  );
}
