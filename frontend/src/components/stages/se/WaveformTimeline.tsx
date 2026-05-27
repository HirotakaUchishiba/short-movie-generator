import { useEffect, useRef } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/plugins/regions";
import TimelinePlugin from "wavesurfer.js/plugins/timeline";
import type { SeItem, SeTrack } from "../../../types";
import { itemsToRegions } from "./timeline-utils";
import { seThumbUrl } from "../../../asset-urls";

interface Props {
  videoUrl: string;
  peaks: number[];
  duration: number;
  items: SeItem[];
  tracks: SeTrack[];
  ts: string;
  thumbCount: number;
  sceneBoundaries: number[];
  onMove: (idx: number, newTime: number) => void;
  onSelect: (idx: number) => void;
}

const CATEGORY_COLOR: Record<string, string> = {
  reaction: "rgba(56,189,248,0.45)", // sky
  sting: "rgba(244,63,94,0.45)", // rose
  transition: "rgba(168,85,247,0.45)", // purple
};

export default function WaveformTimeline({
  videoUrl,
  peaks,
  duration,
  items,
  tracks,
  ts,
  thumbCount,
  sceneBoundaries,
  onMove,
  onSelect,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<ReturnType<typeof RegionsPlugin.create> | null>(
    null,
  );
  // callback は ref 経由で最新化 (wavesurfer の event 購読は ws 構築時の 1 回だけ)。
  const onMoveRef = useRef(onMove);
  const onSelectRef = useRef(onSelect);
  onMoveRef.current = onMove;
  onSelectRef.current = onSelect;

  // 波形 + video を wavesurfer に束ねる (peaks/duration が揃ったら構築)。
  useEffect(() => {
    if (!containerRef.current || !videoRef.current) return;
    if (!peaks.length || duration <= 0) return;
    const regions = RegionsPlugin.create();
    const ws = WaveSurfer.create({
      container: containerRef.current,
      media: videoRef.current,
      peaks: [peaks],
      duration,
      waveColor: "#475569",
      progressColor: "#0ea5e9",
      cursorColor: "#f8fafc",
      height: 72,
      plugins: [regions, TimelinePlugin.create()],
    });
    wsRef.current = ws;
    regionsRef.current = regions;

    regions.on("region-updated", (region) => {
      const idx = Number(region.id);
      if (!Number.isNaN(idx)) onMoveRef.current(idx, region.start);
    });
    regions.on("region-clicked", (region, e) => {
      e.stopPropagation();
      const idx = Number(region.id);
      if (!Number.isNaN(idx)) onSelectRef.current(idx);
    });

    return () => {
      ws.destroy();
      wsRef.current = null;
      regionsRef.current = null;
    };
  }, [peaks, duration]);

  // items / scene 境界を regions に反映 (SE は drag 可、scene 境界は固定マーカー)。
  useEffect(() => {
    const regions = regionsRef.current;
    if (!regions) return;
    regions.clearRegions();
    for (const b of sceneBoundaries) {
      regions.addRegion({
        id: `scene-${b}`,
        start: b,
        end: b + 0.02,
        drag: false,
        resize: false,
        color: "rgba(226,232,240,0.6)",
      });
    }
    for (const r of itemsToRegions(items, tracks)) {
      const track = tracks.find((t) => t.id === r.seId);
      regions.addRegion({
        id: String(r.idx),
        start: r.start,
        end: r.end,
        drag: true,
        resize: false,
        content: track?.title ?? r.seId,
        color: CATEGORY_COLOR[track?.category ?? ""] ?? "rgba(148,163,184,0.4)",
      });
    }
  }, [items, tracks, sceneBoundaries]);

  return (
    <div className="space-y-1">
      <video
        ref={videoRef}
        src={videoUrl}
        controls
        playsInline
        className="w-full max-h-72 bg-black rounded"
      />
      {thumbCount > 0 && (
        <div className="flex w-full overflow-hidden rounded bg-slate-900">
          {Array.from({ length: thumbCount }, (_, i) => (
            <img
              key={i}
              src={seThumbUrl(ts, i)}
              alt=""
              className="h-10 flex-1 object-cover border-r border-slate-800 last:border-r-0"
            />
          ))}
        </div>
      )}
      <div ref={containerRef} className="rounded bg-slate-900 px-1 py-1" />
    </div>
  );
}
