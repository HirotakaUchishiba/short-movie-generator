import { useEffect, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api } from "../../api";
import type { SeTrack, SeItem } from "../../types";

export default function StageSE() {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const bgmApproved = !!ctx.detail.progress.stages.bgm.approved_at;

  const [tracks, setTracks] = useState<SeTrack[]>([]);
  const [items, setItems] = useState<SeItem[]>([]);
  const [pending, setPending] = useState<"save" | "auto" | "bake" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listSe()
      .then((r) => setTracks(r.se))
      .catch((e) => setError(String(e)));
  }, []);

  // 既存の items を metadata.se (detail に含まれる場合) から復元する。
  useEffect(() => {
    const s = (ctx.detail as { se?: { items?: SeItem[] } }).se;
    if (s && Array.isArray(s.items)) setItems(s.items);
  }, [ctx.detail]);

  const onAuto = async () => {
    setPending("auto");
    setError(null);
    try {
      const r = await api.autoSe(ts);
      setItems(r.se.items);
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(null);
    }
  };

  const onSave = async () => {
    setPending("save");
    setError(null);
    try {
      await api.setSe(ts, items);
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(null);
    }
  };

  // 配置を保存してから reels を焼き直す (= se stage 再生成)。
  const onBake = async () => {
    setPending("bake");
    setError(null);
    try {
      await api.setSe(ts, items);
      await api.regen(ts, { stage: "se" });
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(null);
    }
  };

  const updateItem = (idx: number, patch: Partial<SeItem>) => {
    setItems((prev) =>
      prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)),
    );
  };

  const removeItem = (idx: number) => {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  };

  const addItem = () => {
    const first = tracks[0];
    setItems((prev) => [
      ...prev,
      {
        time: 0,
        se_id: first ? first.id : "",
        volume: 0.6,
        source: "manual",
        reason: "",
      },
    ]);
  };

  return (
    <StageGate
      stage="se"
      title="効果音"
      description="字幕 + BGM 済みの動画に効果音を重ねる。emotion / リアクション / シーン境界から配置を自動導出し、UI で取捨・微調整できる。効果音なしでも reels は書き出される。再生成は ffmpeg のみで AI 課金は発生しない。"
    >
      {!bgmApproved ? (
        <div className="card text-center text-slate-400">
          まだ BGM が承認されていません。BGM を承認してから効果音を載せます。
        </div>
      ) : (
        <>
          {error && (
            <div className="rounded border border-rose-700 bg-rose-900/40 p-3 text-sm mb-4">
              {error}
            </div>
          )}
          <div className="card space-y-3">
            <div className="flex gap-2">
              <button
                className="btn"
                onClick={onAuto}
                disabled={pending !== null}
              >
                {pending === "auto" ? "生成中…" : "自動配置を生成"}
              </button>
              <button
                className="btn"
                onClick={addItem}
                disabled={pending !== null || tracks.length === 0}
              >
                + 手動で追加
              </button>
            </div>

            {tracks.length === 0 && (
              <div className="text-sm text-slate-400">
                assets/se/
                に商用利用可の効果音が未配置です。data/se_catalog.json
                に登録すると一覧に出ます。
              </div>
            )}

            {items.length === 0 ? (
              <div className="text-sm text-slate-400">
                効果音は未設定です (= TTS + BGM のまま reels を書き出す)。
              </div>
            ) : (
              items.map((it, idx) => {
                const t = tracks.find((x) => x.id === it.se_id);
                return (
                  <div
                    key={idx}
                    className="border-t border-slate-700 pt-2 space-y-1"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <label className="flex items-center gap-1">
                        <span className="text-sm">秒</span>
                        <input
                          type="number"
                          step="0.1"
                          min={0}
                          className="input text-xs py-1 w-20"
                          value={it.time}
                          onChange={(e) =>
                            updateItem(idx, { time: Number(e.target.value) })
                          }
                        />
                      </label>
                      <select
                        className="input text-xs py-1"
                        value={it.se_id}
                        onChange={(e) =>
                          updateItem(idx, { se_id: e.target.value })
                        }
                      >
                        {tracks.map((tr) => (
                          <option key={tr.id} value={tr.id}>
                            {tr.title} ({tr.category})
                          </option>
                        ))}
                      </select>
                      <label className="flex items-center gap-1">
                        <span className="text-sm">
                          音量 {it.volume.toFixed(2)}
                        </span>
                        <input
                          type="range"
                          min={0}
                          max={1}
                          step={0.01}
                          value={it.volume}
                          onChange={(e) =>
                            updateItem(idx, { volume: Number(e.target.value) })
                          }
                        />
                      </label>
                      <button className="btn" onClick={() => removeItem(idx)}>
                        × 削除
                      </button>
                    </div>
                    <div className="flex items-center gap-2 text-sm text-slate-400">
                      {it.reason && <span>{it.reason}</span>}
                      {t && (
                        <audio
                          controls
                          preload="none"
                          src={`/asset/se/${encodeURIComponent(t.file)}`}
                        />
                      )}
                    </div>
                  </div>
                );
              })
            )}

            <div className="flex gap-2 pt-2 border-t border-slate-700">
              <button
                className="btn"
                onClick={onSave}
                disabled={pending !== null}
              >
                {pending === "save" ? "保存中…" : "配置を保存"}
              </button>
              <button
                className="btn btn-primary"
                onClick={onBake}
                disabled={pending !== null}
              >
                {pending === "bake"
                  ? "焼き直し中…"
                  : "効果音をミックスして reels を焼く"}
              </button>
            </div>
          </div>
        </>
      )}
    </StageGate>
  );
}
