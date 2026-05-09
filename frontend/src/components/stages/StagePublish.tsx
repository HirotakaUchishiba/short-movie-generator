import { useEffect, useState, useCallback } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api, finalVersionAssetUrl } from "../../api";
import type {
  FinalVersion,
  PublishedPost,
  YoutubeChannelInfo,
} from "../../types";

type Platform = "youtube" | "instagram" | "tiktok";
type Privacy = "private" | "unlisted" | "public";

const PLATFORM_LABELS: Record<Platform, string> = {
  youtube: "YouTube Shorts",
  instagram: "Instagram Reels",
  tiktok: "TikTok",
};

const PRIVACY_LABELS: Record<Privacy, string> = {
  private: "private (テスト)",
  unlisted: "unlisted (限定公開)",
  public: "public (公開)",
};

function channelDisplayName(info: YoutubeChannelInfo | null): string {
  if (!info) return "未取得";
  if (info.title && info.channel_id) {
    return `${info.title} (${info.channel_id})`;
  }
  if (info.aud) {
    return `client_id ${info.aud.slice(0, 30)}…`;
  }
  return info.error ?? "取得失敗";
}

export default function StagePublish() {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const stage8Approved = !!ctx.detail.progress.stages.final_import?.approved_at;

  const [history, setHistory] = useState<PublishedPost[]>([]);
  const [canonical, setCanonical] = useState<FinalVersion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyPlatform, setBusyPlatform] = useState<Platform | null>(null);
  const [privacy, setPrivacy] = useState<Privacy>("private");

  // YouTube channel switching state
  const [profiles, setProfiles] = useState<string[]>([]);
  const [profile, setProfile] = useState<string>("default");
  const [channelInfo, setChannelInfo] = useState<YoutubeChannelInfo | null>(
    null,
  );
  const [channelInfoLoading, setChannelInfoLoading] = useState(false);
  const [pendingPlatform, setPendingPlatform] = useState<Platform | null>(null);

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

  // 初回 mount で利用可能 profiles を取得。env 未設定なら空配列が返る。
  useEffect(() => {
    let cancelled = false;
    api
      .youtubeProfiles()
      .then(({ profiles: p }) => {
        if (cancelled) return;
        setProfiles(p);
        if (p.length > 0 && !p.includes(profile)) {
          setProfile(p[0]);
        }
      })
      .catch((e) => {
        console.warn("youtubeProfiles fetch failed:", e);
      });
    return () => {
      cancelled = true;
    };
    // profile は内部で更新するので意図的に依存から外す (= 初回のみ取得)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // profile 切替時に channel info を取得 (= chip / モーダル の表示更新)
  useEffect(() => {
    let cancelled = false;
    setChannelInfoLoading(true);
    api
      .youtubeChannelInfo(profile)
      .then((info) => {
        if (!cancelled) setChannelInfo(info);
      })
      .catch(() => {
        if (!cancelled) setChannelInfo(null);
      })
      .finally(() => {
        if (!cancelled) setChannelInfoLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [profile]);

  const doPublish = async (platform: Platform) => {
    setError(null);
    setBusyPlatform(platform);
    try {
      const job = await api.publish(ts, {
        platform,
        privacy: platform === "youtube" ? privacy : undefined,
        channel: platform === "youtube" ? profile : undefined,
      });
      let done = false;
      while (!done) {
        await new Promise((r) => setTimeout(r, 1500));
        const j = await api.job(job.job_id);
        if (j.status === "completed") {
          done = true;
        } else if (j.status === "failed") {
          throw new Error(j.error || "publish failed");
        }
      }
      await reload();
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyPlatform(null);
    }
  };

  // YouTube だけはモーダル確認を挟む。IG/TikTok は半自動なので直接実行。
  const requestPublish = (platform: Platform) => {
    if (platform === "youtube") {
      setPendingPlatform("youtube");
    } else {
      doPublish(platform);
    }
  };

  const confirmPendingPublish = () => {
    const p = pendingPlatform;
    setPendingPlatform(null);
    if (p) doPublish(p);
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

            {/* YouTube 用の channel chip + selector */}
            <div className="mb-3 text-sm flex flex-wrap items-center gap-3">
              {profiles.length > 1 && (
                <label className="flex items-center gap-2">
                  <span className="text-slate-400">チャンネル:</span>
                  <select
                    value={profile}
                    onChange={(e) => setProfile(e.target.value)}
                    className="bg-slate-800 border border-slate-700 rounded px-2 py-1"
                  >
                    {profiles.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <span className="text-xs text-slate-400">
                投稿先:{" "}
                <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-200">
                  {channelInfoLoading
                    ? "取得中…"
                    : channelDisplayName(channelInfo)}
                </span>
                {channelInfo &&
                  !channelInfo.title &&
                  channelInfo.aud &&
                  !channelInfoLoading && (
                    <span className="ml-2 text-amber-400">
                      ※ 完全なチャンネル名は youtube.readonly scope が必要
                    </span>
                  )}
              </span>
            </div>

            <div className="mb-3 text-sm">
              <label className="mr-2">YouTube 公開範囲:</label>
              <select
                value={privacy}
                onChange={(e) => setPrivacy(e.target.value as Privacy)}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1"
              >
                {(Object.keys(PRIVACY_LABELS) as Privacy[]).map((p) => (
                  <option key={p} value={p}>
                    {PRIVACY_LABELS[p]}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-wrap gap-3">
              {(Object.keys(PLATFORM_LABELS) as Platform[]).map((p) => (
                <button
                  key={p}
                  className="btn-primary"
                  disabled={busyPlatform !== null}
                  onClick={() => requestPublish(p)}
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
                  {history.map((p, i) => (
                    <tr key={i}>
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

      {/* YouTube 公開前の確認モーダル */}
      {pendingPlatform === "youtube" && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={() => setPendingPlatform(null)}
        >
          <div
            className="card max-w-md w-full mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold mb-3">
              YouTube に投稿しますか?
            </h3>
            <dl className="text-sm bg-slate-800 rounded p-3 mb-4 space-y-1">
              <div className="flex">
                <dt className="text-slate-400 w-20">投稿先:</dt>
                <dd className="flex-1">{channelDisplayName(channelInfo)}</dd>
              </div>
              <div className="flex">
                <dt className="text-slate-400 w-20">profile:</dt>
                <dd className="flex-1">{channelInfo?.profile ?? profile}</dd>
              </div>
              <div className="flex">
                <dt className="text-slate-400 w-20">公開範囲:</dt>
                <dd className="flex-1">{PRIVACY_LABELS[privacy]}</dd>
              </div>
            </dl>
            {channelInfo && !channelInfo.title && (
              <p className="text-xs text-amber-400 mb-3">
                ※ チャンネル名 / channel_id は scope 不足で取得できていません (=
                refresh_token に youtube.readonly を追加すると完全表示)。
                profile と client_id (aud) で投稿先は判別できています。
              </p>
            )}
            <div className="flex gap-2 justify-end">
              <button
                className="btn-secondary"
                onClick={() => setPendingPlatform(null)}
              >
                キャンセル
              </button>
              <button className="btn-primary" onClick={confirmPendingPublish}>
                公開する
              </button>
            </div>
          </div>
        </div>
      )}
    </StageGate>
  );
}
