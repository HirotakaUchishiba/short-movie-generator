import { useEffect, useRef, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api } from "../../api";
import type { SeTrack, SeItem, BgmTrack } from "../../types";
import MultiTrackTimeline from "./se/MultiTrackTimeline";
import {
  addItemAt,
  moveItemTime,
  clampNoOverlap,
  setItemClip,
  computeSceneBlocks,
  computeSubtitleBlocks,
  type SceneLike,
} from "./se/timeline-utils";
import { reelsAssetUrl } from "../../asset-urls";

export default function StageSE() {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const bgmApproved = !!ctx.detail.progress.stages.bgm.approved_at;
  const seRegen = (
    ctx.detail.progress.stages.se as { regen_count?: number } | undefined
  )?.regen_count;

  const [tracks, setTracks] = useState<SeTrack[]>([]);
  const [bgmTracks, setBgmTracks] = useState<BgmTrack[]>([]);
  const [items, setItems] = useState<SeItem[]>([]);
  const [peaks, setPeaks] = useState<number[]>([]);
  const [duration, setDuration] = useState(0);
  const [sceneOffsets, setSceneOffsets] = useState<number[]>([]);
  const [thumbCount, setThumbCount] = useState(0);
  const [thumbInterval, setThumbInterval] = useState(1);
  const [selectedIdxs, setSelectedIdxs] = useState<number[]>([]);
  const [baking, setBaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bakeTimer = useRef<number | null>(null);

  useEffect(() => {
    api
      .listSe()
      .then((r) => setTracks(r.se))
      .catch((e) => setError(String(e)));
    api
      .listBgm()
      .then((r) => setBgmTracks(r.bgm))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!bgmApproved) return;
    api
      .getSeWaveform(ts)
      .then((r) => {
        setPeaks(r.peaks);
        setDuration(r.duration);
        setSceneOffsets(r.scene_offsets ?? []);
      })
      .catch(() => undefined);
    api
      .getSeThumbnails(ts)
      .then((r) => {
        setThumbCount(r.count);
        setThumbInterval(r.interval_sec || 1);
      })
      .catch(() => undefined);
  }, [ts, bgmApproved]);

  useEffect(() => {
    const s = (ctx.detail as { se?: { items?: SeItem[] } }).se;
    if (s && Array.isArray(s.items)) setItems(s.items);
  }, [ctx.detail]);

  const scenes: SceneLike[] =
    (ctx.detail as { screenplay?: { scenes?: SceneLike[] } }).screenplay
      ?.scenes ?? [];
  const subtitleBlocks = computeSubtitleBlocks(scenes, sceneOffsets);
  const sceneBlocks = computeSceneBlocks(scenes, sceneOffsets);

  const bgmId = (ctx.detail as { bgm?: { id?: string } }).bgm?.id;
  const bgmLabel =
    bgmId && bgmId !== "none"
      ? (bgmTracks.find((b) => b.id === bgmId)?.title ?? bgmId)
      : null;

  // 編集操作で items を変えるたびに呼ぶ。debounce して setSe + reels 焼き直しを
  // 自動実行する (= 効果音を重ねた / 消した時点で動画に即反映)。
  const applyItems = (next: SeItem[]) => {
    setItems(next);
    if (bakeTimer.current) window.clearTimeout(bakeTimer.current);
    bakeTimer.current = window.setTimeout(() => void autoBake(next), 700);
  };

  const autoBake = async (next: SeItem[]) => {
    setBaking(true);
    setError(null);
    try {
      await api.setSe(ts, next);
      await api.regen(ts, { stage: "se" });
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBaking(false);
    }
  };

  const onSelect = (idx: number, additive: boolean) => {
    setSelectedIdxs((prev) => {
      if (additive) {
        return prev.includes(idx)
          ? prev.filter((i) => i !== idx)
          : [...prev, idx];
      }
      return [idx];
    });
  };

  const removeMany = (idxs: number[]) => {
    const set = new Set(idxs);
    applyItems(items.filter((_, i) => !set.has(i)));
    setSelectedIdxs([]);
  };

  // 単一選択のときだけ詳細パネルで編集する。
  const selIdx = selectedIdxs.length === 1 ? selectedIdxs[0] : null;
  const selected = selIdx !== null ? (items[selIdx] ?? null) : null;
  const updateSelected = (patch: Partial<SeItem>) => {
    if (selIdx === null) return;
    applyItems(items.map((it, i) => (i === selIdx ? { ...it, ...patch } : it)));
  };

  return (
    <StageGate
      stage="se"
      title="効果音"
      description="字幕・映像・BGM・効果音をタイムラインで見ながら効果音を配置・移動・長さ変更・削除する。変更は自動で動画 (reels) に反映される。ffmpeg のみで AI 課金は発生しない。"
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
          {tracks.length === 0 && (
            <div className="text-sm text-slate-400 mb-2">
              assets/se/ に効果音が未配置です。data/se_catalog.json
              に登録すると選べます。
            </div>
          )}
          <div className="card space-y-3">
            <div>
              <div className="text-sm text-slate-400 mb-1">
                効果音をタイムラインの効果音トラックにドラッグして配置
              </div>
              <div className="grid grid-cols-3 gap-2 max-h-40 overflow-y-auto">
                {tracks.map((t) => (
                  <div
                    key={t.id}
                    draggable
                    onDragStart={(e) => e.dataTransfer.setData("se_id", t.id)}
                    className="rounded border border-slate-700 bg-slate-800 p-2 text-xs cursor-grab"
                  >
                    <div className="truncate font-medium">{t.title}</div>
                    <div className="text-slate-500">{t.category}</div>
                    <audio
                      controls
                      preload="none"
                      src={`/asset/se/${encodeURIComponent(t.file)}`}
                      className="w-full h-6 mt-1"
                    />
                  </div>
                ))}
              </div>
            </div>
            <MultiTrackTimeline
              videoUrl={reelsAssetUrl(ts, seRegen)}
              peaks={peaks}
              duration={duration}
              items={items}
              tracks={tracks}
              ts={ts}
              thumbCount={thumbCount}
              thumbInterval={thumbInterval}
              subtitleBlocks={subtitleBlocks}
              sceneBlocks={sceneBlocks}
              bgmLabel={bgmLabel}
              selectedIdxs={selectedIdxs}
              onMove={(idx, t) =>
                applyItems(
                  moveItemTime(
                    items,
                    idx,
                    clampNoOverlap(items, tracks, idx, t),
                  ),
                )
              }
              onSelect={onSelect}
              onRemoveMany={removeMany}
              onResize={(idx, cs, ce, t) => {
                let next = setItemClip(items, tracks, idx, cs, ce);
                next = moveItemTime(next, idx, Math.max(0, t));
                applyItems(next);
              }}
              onAddAtPlayhead={(t) => {
                const f = tracks[0];
                if (!f) return;
                let next = addItemAt(items, t, f.id, 0.6);
                const newIdx = next.length - 1;
                next = moveItemTime(
                  next,
                  newIdx,
                  clampNoOverlap(next, tracks, newIdx, t),
                );
                setSelectedIdxs([newIdx]);
                applyItems(next);
              }}
              onDropSe={(seId, t) => {
                let next = addItemAt(items, t, seId, 0.6);
                const newIdx = next.length - 1;
                next = moveItemTime(
                  next,
                  newIdx,
                  clampNoOverlap(next, tracks, newIdx, t),
                );
                setSelectedIdxs([newIdx]);
                applyItems(next);
              }}
            />

            <div className="text-sm text-slate-400">
              {baking
                ? "🔄 動画に反映中…"
                : selectedIdxs.length > 1
                  ? `${selectedIdxs.length} 個選択中 (Delete で一括削除)`
                  : "✓ 追加・移動・長さ変更・削除は自動で動画 (reels) に反映されます"}
            </div>

            {selected && selIdx !== null ? (
              <div className="border-t border-slate-700 pt-3 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-slate-400">
                    @{selected.time.toFixed(2)}s
                  </span>
                  <select
                    className="input text-sm py-1"
                    value={selected.se_id}
                    onChange={(e) => updateSelected({ se_id: e.target.value })}
                  >
                    {tracks.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.title} ({t.category})
                      </option>
                    ))}
                  </select>
                  <label className="flex items-center gap-1">
                    <span className="text-sm">
                      音量 {selected.volume.toFixed(2)}
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.01}
                      value={selected.volume}
                      onChange={(e) =>
                        updateSelected({ volume: Number(e.target.value) })
                      }
                    />
                  </label>
                  <button className="btn" onClick={() => removeMany([selIdx])}>
                    × 削除
                  </button>
                </div>
                {selected.reason && (
                  <div className="text-sm text-slate-400">
                    {selected.reason}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-sm text-slate-400 border-t border-slate-700 pt-3">
                効果音をクリックで選択・ドラッグで移動・両端ドラッグで長さ変更。Cmd/Ctrl+クリックで複数選択、Delete
                で削除。「⊕ 再生位置に効果音を追加」で新規追加。
              </div>
            )}
          </div>
        </>
      )}
    </StageGate>
  );
}
