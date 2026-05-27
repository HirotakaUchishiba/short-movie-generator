import { useEffect, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api } from "../../api";
import type { BgmTrack } from "../../types";

const NONE_ID = "none";

export default function StageBGM() {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const overlayApproved = !!ctx.detail.progress.stages.overlay.approved_at;

  const [tracks, setTracks] = useState<BgmTrack[]>([]);
  const [selId, setSelId] = useState<string>(NONE_ID);
  const [volume, setVolume] = useState(0.18);
  const [ducking, setDucking] = useState(true);
  const [pending, setPending] = useState<"save" | "bake" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listBgm()
      .then((r) => setTracks(r.bgm))
      .catch((e) => setError(String(e)));
  }, []);

  // 既存の選択を metadata.bgm (detail に含まれる場合) から復元する。
  useEffect(() => {
    const b = (
      ctx.detail as {
        bgm?: { id?: string; volume?: number; ducking?: boolean };
      }
    ).bgm;
    if (b && typeof b === "object") {
      if (b.id) setSelId(b.id);
      if (typeof b.volume === "number") setVolume(b.volume);
      if (typeof b.ducking === "boolean") setDucking(b.ducking);
    }
  }, [ctx.detail]);

  const persist = async () => {
    await api.setBgm(ts, { id: selId, volume, ducking });
  };

  const onSave = async () => {
    setPending("save");
    setError(null);
    try {
      await persist();
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(null);
    }
  };

  // 選択を保存してから reels を焼き直す (= bgm stage 再生成)。
  const onBake = async () => {
    setPending("bake");
    setError(null);
    try {
      await persist();
      await api.regen(ts, { stage: "bgm" });
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(null);
    }
  };

  return (
    <StageGate
      stage="bgm"
      title="BGM"
      description="字幕焼き込み済みの動画に BGM をミックスする。発話中は BGM を自動で下げる (ダッキング)。「BGM なし」を選ぶと TTS 音声のみのまま reels を書き出す。再生成は ffmpeg のみで AI 課金は発生しない。"
    >
      {!overlayApproved ? (
        <div className="card text-center text-slate-400">
          まだ 字幕 が承認されていません。字幕を承認してから BGM
          をミックスします。
        </div>
      ) : (
        <>
          {error && (
            <div className="rounded border border-rose-700 bg-rose-900/40 p-3 text-sm mb-4">
              {error}
            </div>
          )}
          <div className="card space-y-3">
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="bgm"
                checked={selId === NONE_ID}
                onChange={() => setSelId(NONE_ID)}
              />
              <span>BGM なし (TTS 音声のみ)</span>
            </label>

            {tracks.length === 0 && (
              <div className="text-sm text-slate-400">
                assets/bgm/
                に商用利用可の音源が未配置です。data/bgm_catalog.json に
                登録すると一覧に出ます。
              </div>
            )}

            {tracks.map((t) => (
              <div key={t.id} className="border-t border-slate-700 pt-2">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="bgm"
                    checked={selId === t.id}
                    onChange={() => setSelId(t.id)}
                  />
                  <span>
                    {t.title}{" "}
                    <span className="text-slate-400 text-sm">
                      ({t.mood} / {t.license})
                    </span>
                  </span>
                </label>
                <audio
                  className="mt-1 w-full"
                  controls
                  preload="none"
                  src={`/asset/bgm/${encodeURIComponent(t.file)}`}
                />
              </div>
            ))}

            <div className="border-t border-slate-700 pt-3 space-y-2">
              <label className="flex items-center gap-2">
                <span className="w-28">音量 {volume.toFixed(2)}</span>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={volume}
                  disabled={selId === NONE_ID}
                  onChange={(e) => setVolume(Number(e.target.value))}
                />
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={ducking}
                  disabled={selId === NONE_ID}
                  onChange={(e) => setDucking(e.target.checked)}
                />
                <span>発話中に BGM を下げる (ダッキング)</span>
              </label>
            </div>

            <div className="flex gap-2 pt-2">
              <button
                className="btn"
                onClick={onSave}
                disabled={pending !== null}
              >
                {pending === "save" ? "保存中…" : "選択を保存"}
              </button>
              <button
                className="btn btn-primary"
                onClick={onBake}
                disabled={pending !== null}
              >
                {pending === "bake"
                  ? "焼き直し中…"
                  : "BGM をミックスして reels を焼く"}
              </button>
            </div>
          </div>
        </>
      )}
    </StageGate>
  );
}
