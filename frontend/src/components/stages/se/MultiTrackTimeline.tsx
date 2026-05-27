import { useEffect, useRef, useState } from "react";
import type { SeItem, SeTrack } from "../../../types";
import type { TimelineBlock } from "./timeline-utils";
import { itemsToRegions } from "./timeline-utils";
import { seThumbUrl } from "../../../asset-urls";

// CapCut 風マルチトラック timeline。横軸 = 時間 (pxPerSec 可変スケール + 横スクロール)。
// 字幕 / 映像サムネ / 波形 / 効果音 (ドラッグ移動 + 端ドラッグ trim) / BGM を縦に積む。
// playhead は <video> の currentTime と同期。効果音のみ編集可能 (他は参照表示)。
interface Props {
  videoUrl: string;
  peaks: number[];
  duration: number;
  items: SeItem[];
  tracks: SeTrack[];
  ts: string;
  thumbCount: number;
  thumbInterval: number;
  subtitleBlocks: TimelineBlock[];
  sceneBlocks: TimelineBlock[];
  bgmLabel: string | null;
  selectedIdxs: number[];
  onMove: (idx: number, time: number) => void;
  onSelect: (idx: number, additive: boolean) => void;
  onRemoveMany: (idxs: number[]) => void;
  onResize: (
    idx: number,
    clipStart: number,
    clipEnd: number,
    newTime: number,
  ) => void;
  onAddAtPlayhead: (time: number) => void;
  onDropSe: (seId: string, time: number) => void;
}

const CATEGORY_COLOR: Record<string, string> = {
  reaction: "rgba(56,189,248,0.85)",
  sting: "rgba(244,63,94,0.85)",
  transition: "rgba(168,85,247,0.85)",
};

function fmt(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export default function MultiTrackTimeline({
  videoUrl,
  peaks,
  duration,
  items,
  tracks,
  ts,
  thumbCount,
  thumbInterval,
  subtitleBlocks,
  sceneBlocks,
  bgmLabel,
  selectedIdxs,
  onMove,
  onSelect,
  onRemoveMany,
  onResize,
  onAddAtPlayhead,
  onDropSe,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const waveRef = useRef<HTMLCanvasElement>(null);
  const [playhead, setPlayhead] = useState(0);
  const [pxPerSec, setPxPerSec] = useState(90);

  // playhead を video.currentTime に追従 (rAF)。
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = videoRef.current;
      if (v) setPlayhead(v.currentTime);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // 選択中の効果音を Delete / Backspace で一括削除 (input/select 編集中は無視)。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (!selectedIdxs.length) return;
      e.preventDefault();
      onRemoveMany(selectedIdxs);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedIdxs, onRemoveMany]);

  const width = Math.max(Math.ceil(duration * pxPerSec), 320);
  const regions = itemsToRegions(items, tracks);

  // 波形 canvas を描画 (幅は pxPerSec に追従)。
  useEffect(() => {
    const cv = waveRef.current;
    if (!cv) return;
    const g = cv.getContext("2d");
    if (!g) return;
    cv.width = width;
    cv.height = 40;
    g.clearRect(0, 0, width, 40);
    if (!peaks.length) return;
    g.fillStyle = "#0ea5e9";
    const barW = width / peaks.length;
    peaks.forEach((p, i) => {
      const h = Math.max(p * 38, 1);
      g.fillRect(i * barW, (40 - h) / 2, Math.max(barW - 0.5, 0.5), h);
    });
  }, [peaks, width]);

  const seekTo = (clientX: number, el: HTMLElement) => {
    const rect = el.getBoundingClientRect();
    const t = Math.max(0, (clientX - rect.left) / pxPerSec);
    if (videoRef.current) videoRef.current.currentTime = t;
  };

  // SE 本体ドラッグ = 移動 (Cmd/Ctrl は追加選択のみで移動しない)。
  const onSeMouseDown = (e: React.MouseEvent, idx: number, time: number) => {
    e.stopPropagation();
    const additive = e.metaKey || e.ctrlKey;
    onSelect(idx, additive);
    if (additive) return;
    const startX = e.clientX;
    const move = (ev: MouseEvent) => {
      onMove(idx, Math.max(0, time + (ev.clientX - startX) / pxPerSec));
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  // 端ドラッグ = trim。end は clip_end を伸縮、start は clip_start と time を同時に。
  const onResizeStart = (
    e: React.MouseEvent,
    idx: number,
    edge: "start" | "end",
  ) => {
    e.stopPropagation();
    const it = items[idx];
    const full = tracks.find((t) => t.id === it.se_id)?.duration_sec ?? 0.3;
    const cs0 = it.clip_start ?? 0;
    const ce0 = it.clip_end ?? full;
    const t0 = it.time;
    const startX = e.clientX;
    const move = (ev: MouseEvent) => {
      const d = (ev.clientX - startX) / pxPerSec;
      if (edge === "end") {
        onResize(idx, cs0, ce0 + d, t0);
      } else {
        onResize(idx, cs0 + d, ce0, t0 + d);
      }
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const ticks: number[] = [];
  for (let s = 0; s <= duration; s += 3) ticks.push(s);

  return (
    <div className="space-y-2">
      <video
        key={videoUrl}
        ref={videoRef}
        src={videoUrl}
        controls
        playsInline
        className="w-full max-h-72 bg-black rounded"
      />
      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          className="btn"
          onClick={() => onAddAtPlayhead(videoRef.current?.currentTime ?? 0)}
        >
          ⊕ 再生位置に効果音を追加
        </button>
        <label className="flex items-center gap-1">
          <span className="text-xs text-slate-400">ズーム</span>
          <input
            type="range"
            min={30}
            max={240}
            step={10}
            value={pxPerSec}
            onChange={(e) => setPxPerSec(Number(e.target.value))}
          />
        </label>
        <span className="text-xs text-slate-500">
          Cmd/Ctrl+クリックで複数選択 / 端ドラッグで長さ変更 / Delete で削除
        </span>
      </div>

      <div className="overflow-x-auto rounded border border-slate-800 bg-slate-900">
        <div className="relative" style={{ width }}>
          {/* ルーラー */}
          <div className="relative h-5 border-b border-slate-700">
            {ticks.map((s) => (
              <div
                key={s}
                className="absolute top-0 text-[10px] text-slate-400"
                style={{ left: s * pxPerSec }}
              >
                |{fmt(s)}
              </div>
            ))}
          </div>

          {/* 字幕トラック (チャンク単位) */}
          <div
            className="relative h-7 border-b border-slate-800"
            onClick={(e) => seekTo(e.clientX, e.currentTarget)}
          >
            {subtitleBlocks.map((b, i) => (
              <div
                key={i}
                className="absolute top-0.5 h-6 rounded bg-orange-800/80 text-[10px] text-white px-1 truncate"
                style={{
                  left: b.start * pxPerSec,
                  width: Math.max((b.end - b.start) * pxPerSec, 4),
                }}
                title={b.label}
              >
                {b.label}
              </div>
            ))}
          </div>

          {/* 映像トラック (サムネ + scene ラベル) */}
          <div
            className="relative h-12 border-b border-slate-800 bg-black"
            onClick={(e) => seekTo(e.clientX, e.currentTarget)}
          >
            {Array.from({ length: thumbCount }, (_, i) => (
              <img
                key={i}
                src={seThumbUrl(ts, i)}
                alt=""
                className="absolute top-0 h-12 object-cover"
                style={{
                  left: i * thumbInterval * pxPerSec,
                  width: thumbInterval * pxPerSec,
                }}
              />
            ))}
            {sceneBlocks.map((b, i) => (
              <div
                key={i}
                className="absolute top-0 h-3 border-l border-cyan-500 pl-0.5 text-[9px] text-cyan-200"
                style={{ left: b.start * pxPerSec }}
              >
                {b.label}
              </div>
            ))}
          </div>

          {/* 波形トラック (bgm_mixed の音声) */}
          <div className="relative h-10 border-b border-slate-800">
            <canvas ref={waveRef} className="absolute top-0 left-0" />
          </div>

          {/* 効果音トラック (ドラッグ移動 + 端 trim) */}
          <div
            className="relative h-10 border-b border-slate-800"
            onClick={(e) => seekTo(e.clientX, e.currentTarget)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const seId = e.dataTransfer.getData("se_id");
              if (!seId) return;
              const rect = e.currentTarget.getBoundingClientRect();
              onDropSe(seId, Math.max(0, (e.clientX - rect.left) / pxPerSec));
            }}
          >
            {regions.map((r) => {
              const track = tracks.find((t) => t.id === r.seId);
              const selected = selectedIdxs.includes(r.idx);
              return (
                <div
                  key={r.idx}
                  className={`absolute top-1 h-8 rounded px-1 text-[10px] text-white truncate cursor-grab ${
                    selected ? "ring-2 ring-white" : ""
                  }`}
                  style={{
                    left: r.start * pxPerSec,
                    width: Math.max((r.end - r.start) * pxPerSec, 8),
                    background:
                      CATEGORY_COLOR[track?.category ?? ""] ??
                      "rgba(148,163,184,0.7)",
                  }}
                  title={track?.title ?? r.seId}
                  onMouseDown={(e) => onSeMouseDown(e, r.idx, r.start)}
                >
                  <div
                    className="absolute left-0 top-0 h-full w-1.5 cursor-ew-resize bg-black/30"
                    onMouseDown={(e) => onResizeStart(e, r.idx, "start")}
                  />
                  {track?.title ?? r.seId}
                  <div
                    className="absolute right-0 top-0 h-full w-1.5 cursor-ew-resize bg-black/30"
                    onMouseDown={(e) => onResizeStart(e, r.idx, "end")}
                  />
                </div>
              );
            })}
          </div>

          {/* BGM トラック (全体に 1 本、参照) */}
          <div className="relative h-7">
            {bgmLabel && (
              <div
                className="absolute top-1 h-5 rounded bg-indigo-700/70 text-[10px] text-white px-1 truncate"
                style={{ left: 0, width: duration * pxPerSec }}
              >
                ♪ {bgmLabel}
              </div>
            )}
          </div>

          {/* playhead */}
          <div
            className="absolute top-0 bottom-0 w-px bg-white pointer-events-none"
            style={{ left: playhead * pxPerSec }}
          />
        </div>
      </div>
    </div>
  );
}
