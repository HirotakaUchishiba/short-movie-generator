import { useEffect, useRef, useState } from "react";
import type { SeItem, SeTrack } from "../../../types";
import type { TimelineBlock } from "./timeline-utils";
import { itemsToRegions } from "./timeline-utils";
import { seThumbUrl } from "../../../asset-urls";

// CapCut 風マルチトラック timeline。横軸 = 時間 (PX_PER_SEC 固定スケール + 横スクロール)。
// 字幕 / 映像サムネ / 波形 / 効果音 (ドラッグ可) / BGM を縦に積む。playhead は
// <video> の currentTime と同期。effects のみ編集可能 (他は参照表示)。
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
  selectedIdx: number | null;
  onMove: (idx: number, time: number) => void;
  onSelect: (idx: number) => void;
  onAddAtPlayhead: (time: number) => void;
}

const PX_PER_SEC = 90;

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
  selectedIdx,
  onMove,
  onSelect,
  onAddAtPlayhead,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const waveRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<{ idx: number; startX: number; orig: number } | null>(
    null,
  );
  const [playhead, setPlayhead] = useState(0);

  const width = Math.max(Math.ceil(duration * PX_PER_SEC), 320);
  const regions = itemsToRegions(items, tracks);

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

  // 波形 canvas を描画。
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
    const t = Math.max(0, (clientX - rect.left) / PX_PER_SEC);
    if (videoRef.current) videoRef.current.currentTime = t;
  };

  const onSeMouseDown = (e: React.MouseEvent, idx: number, time: number) => {
    e.stopPropagation();
    onSelect(idx);
    dragRef.current = { idx, startX: e.clientX, orig: time };
    const move = (ev: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const t = Math.max(0, d.orig + (ev.clientX - d.startX) / PX_PER_SEC);
      onMove(d.idx, t);
    };
    const up = () => {
      dragRef.current = null;
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
        ref={videoRef}
        src={videoUrl}
        controls
        playsInline
        className="w-full max-h-72 bg-black rounded"
      />
      <button
        type="button"
        className="btn"
        onClick={() => onAddAtPlayhead(videoRef.current?.currentTime ?? 0)}
      >
        ⊕ 再生位置に効果音を追加
      </button>

      <div className="overflow-x-auto rounded border border-slate-800 bg-slate-900">
        <div className="relative" style={{ width }}>
          {/* ルーラー */}
          <div className="relative h-5 border-b border-slate-700">
            {ticks.map((s) => (
              <div
                key={s}
                className="absolute top-0 text-[10px] text-slate-400"
                style={{ left: s * PX_PER_SEC }}
              >
                |{fmt(s)}
              </div>
            ))}
          </div>

          {/* 字幕トラック */}
          <div
            className="relative h-7 border-b border-slate-800"
            onClick={(e) => seekTo(e.clientX, e.currentTarget)}
          >
            {subtitleBlocks.map((b, i) => (
              <div
                key={i}
                className="absolute top-0.5 h-6 rounded bg-orange-800/80 text-[10px] text-white px-1 overflow-hidden whitespace-nowrap"
                style={{
                  left: b.start * PX_PER_SEC,
                  width: Math.max((b.end - b.start) * PX_PER_SEC, 6),
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
                  left: i * thumbInterval * PX_PER_SEC,
                  width: thumbInterval * PX_PER_SEC,
                }}
              />
            ))}
            {sceneBlocks.map((b, i) => (
              <div
                key={i}
                className="absolute top-0 h-3 border-l border-cyan-500 pl-0.5 text-[9px] text-cyan-200"
                style={{ left: b.start * PX_PER_SEC }}
              >
                {b.label}
              </div>
            ))}
          </div>

          {/* 波形トラック (bgm_mixed の音声) */}
          <div className="relative h-10 border-b border-slate-800">
            <canvas ref={waveRef} className="absolute top-0 left-0" />
          </div>

          {/* 効果音トラック (ドラッグ可) */}
          <div
            className="relative h-10 border-b border-slate-800"
            onClick={(e) => seekTo(e.clientX, e.currentTarget)}
          >
            {regions.map((r) => {
              const track = tracks.find((t) => t.id === r.seId);
              return (
                <div
                  key={r.idx}
                  className={`absolute top-1 h-8 rounded px-1 text-[10px] text-white overflow-hidden whitespace-nowrap cursor-grab ${
                    r.idx === selectedIdx ? "ring-2 ring-white" : ""
                  }`}
                  style={{
                    left: r.start * PX_PER_SEC,
                    width: Math.max((r.end - r.start) * PX_PER_SEC, 8),
                    background:
                      CATEGORY_COLOR[track?.category ?? ""] ??
                      "rgba(148,163,184,0.7)",
                  }}
                  title={track?.title ?? r.seId}
                  onMouseDown={(e) => onSeMouseDown(e, r.idx, r.start)}
                >
                  {track?.title ?? r.seId}
                </div>
              );
            })}
          </div>

          {/* BGM トラック (全体に 1 本、参照) */}
          <div className="relative h-7">
            {bgmLabel && (
              <div
                className="absolute top-1 h-5 rounded bg-indigo-700/70 text-[10px] text-white px-1 overflow-hidden whitespace-nowrap"
                style={{ left: 0, width: duration * PX_PER_SEC }}
              >
                ♪ {bgmLabel}
              </div>
            )}
          </div>

          {/* playhead */}
          <div
            className="absolute top-0 bottom-0 w-px bg-white pointer-events-none"
            style={{ left: playhead * PX_PER_SEC }}
          />
        </div>
      </div>
    </div>
  );
}
