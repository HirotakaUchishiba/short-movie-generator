import { useEffect, useRef, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api } from "../../api";
import type { SeTrack, SeItem, BgmTrack } from "../../types";
import MultiTrackTimeline from "./se/MultiTrackTimeline";
import {
  addItemAt,
  moveItemTime,
  removeItemAt,
  computeSceneBlocks,
  computeSubtitleBlocks,
  type SceneLike,
} from "./se/timeline-utils";
import { bgmMixedAssetUrl } from "../../asset-urls";

export default function StageSE() {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const bgmApproved = !!ctx.detail.progress.stages.bgm.approved_at;

  const [tracks, setTracks] = useState<SeTrack[]>([]);
  const [bgmTracks, setBgmTracks] = useState<BgmTrack[]>([]);
  const [items, setItems] = useState<SeItem[]>([]);
  const [peaks, setPeaks] = useState<number[]>([]);
  const [duration, setDuration] = useState(0);
  const [sceneOffsets, setSceneOffsets] = useState<number[]>([]);
  const [thumbCount, setThumbCount] = useState(0);
  const [thumbInterval, setThumbInterval] = useState(1);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
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

  // 波形 + 実尺 scene_offsets + サムネは bgm_mixed ベースで bake では変わらないので
  // bgm 承認時に 1 回取得。scene_offsets は字幕 / scene ブロックの正確な配置に使う。
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

  // 既存 items を metadata.se から復元 (= 編集トリガにはしない)。
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

  const selected = selectedIdx !== null ? (items[selectedIdx] ?? null) : null;
  const updateSelected = (patch: Partial<SeItem>) => {
    if (selectedIdx === null) return;
    applyItems(
      items.map((it, i) => (i === selectedIdx ? { ...it, ...patch } : it)),
    );
  };

  const removeAt = (idx: number) => {
    applyItems(removeItemAt(items, idx));
    setSelectedIdx(null);
  };

  return (
    <StageGate
      stage="se"
      title="効果音"
      description="字幕・映像・BGM・効果音をタイムラインで見ながら効果音を配置・移動・削除する。変更は自動で動画 (reels) に反映される。ffmpeg のみで AI 課金は発生しない。"
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
            <MultiTrackTimeline
              videoUrl={bgmMixedAssetUrl(ts)}
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
              selectedIdx={selectedIdx}
              onMove={(idx, t) => applyItems(moveItemTime(items, idx, t))}
              onSelect={setSelectedIdx}
              onRemove={removeAt}
              onAddAtPlayhead={(t) => {
                const f = tracks[0];
                if (!f) return;
                const next = addItemAt(items, t, f.id, 0.6);
                setSelectedIdx(next.length - 1);
                applyItems(next);
              }}
            />

            <div className="text-sm text-slate-400">
              {baking
                ? "🔄 動画に反映中…"
                : "✓ 追加・移動・削除は自動で動画 (reels) に反映されます"}
            </div>

            {selected ? (
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
                  <button
                    className="btn"
                    onClick={() => removeAt(selectedIdx!)}
                  >
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
                効果音トラックのブロックをクリックで編集・ドラッグで移動。「⊕
                再生位置に効果音を追加」で新規追加。選択中は Delete キーで削除。
              </div>
            )}
          </div>
        </>
      )}
    </StageGate>
  );
}
