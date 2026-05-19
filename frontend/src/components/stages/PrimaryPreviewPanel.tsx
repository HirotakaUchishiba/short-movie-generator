// StageOverlay.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// ffmpeg-baked overlaid.mp4 を <video> で再生する primary preview。videoRef を
// 親 (StageOverlay) で保持し、currentTime ベースで chunk snap に使う。
// SubtitleYPositionGuide は video 領域上に重ねて Y 位置編集の視覚的
// フィードバックを提供する。

import { overlayAssetUrl } from "../../api";
import { SubtitleYPositionGuide } from "./SubtitleYPositionEditor";

export function PrimaryPreviewPanel({
  ts,
  bumpKey,
  videoRef,
  videoHeight,
  currentSubtitleY,
}: {
  ts: string;
  bumpKey: number;
  videoRef: React.MutableRefObject<HTMLVideoElement | null>;
  videoHeight: number;
  currentSubtitleY: number;
}) {
  // bumpKey が変わった時 (= 再焼き直し直後) に強制再ロードして cache を回避する。
  const src = overlayAssetUrl(ts, bumpKey);
  return (
    <div className="max-w-md mx-auto mb-3">
      <div className="aspect-[9/16] bg-slate-950 overflow-hidden rounded relative">
        <video
          ref={videoRef}
          key={bumpKey}
          src={src}
          controls
          loop
          className="w-full h-full object-contain"
        />
        <SubtitleYPositionGuide
          videoHeight={videoHeight}
          currentY={currentSubtitleY}
        />
      </div>
    </div>
  );
}
