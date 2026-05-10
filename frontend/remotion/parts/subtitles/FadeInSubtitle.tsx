import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

// "fade_in" subtitle part.
// 表示開始から短時間 (= fadeDurationFrames) かけて opacity を 0 → 1 にフェードイン。
// 既存 minimal と同じ視認性を保ちつつ、現れ方を柔らかくする。
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.3

export type FadeInSubtitleProps = {
  text: string;
  fontSize?: number;
  fontColor?: string;
  borderColor?: string;
  borderWidth?: number;
  yFromBottom?: number;
  // 既定 8 frame (= 60fps で約 0.13 秒)。0 で fade なし
  fadeDurationFrames?: number;
  emotion?: string;
};

export const FadeInSubtitle: React.FC<FadeInSubtitleProps> = ({
  text,
  fontSize = 76,
  fontColor = "#FFFFFF",
  borderColor = "#000000",
  borderWidth = 6,
  yFromBottom = 950,
  fadeDurationFrames = 8,
}) => {
  const frame = useCurrentFrame();
  // <Sequence> 配下では frame=0 が表示開始フレームなので、そのまま fade に使える
  const opacity = interpolate(
    frame,
    [0, Math.max(1, fadeDurationFrames)],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  // ffmpeg drawtext の `y` はテキスト top 起点。Remotion で同じ位置にするには
  // paddingBottom = (yFromBottom - fontSize) で justifyContent flex-end する
  // (= MinimalSubtitle と同じ算出)。
  const paddingBottom = Math.max(0, yFromBottom - fontSize);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom,
        pointerEvents: "none",
        opacity,
      }}
    >
      <div
        style={{
          fontFamily:
            "'ヒラギノ角ゴシック W7', 'Hiragino Sans', 'Yu Gothic', sans-serif",
          fontWeight: 700,
          fontSize,
          color: fontColor,
          WebkitTextStroke: `${borderWidth}px ${borderColor}`,
          paintOrder: "stroke fill",
          textAlign: "center",
          lineHeight: 1.2,
          // ffmpeg drawtext は自動折返ししないため Remotion 側も `pre` で揃える
          // (= \n は line break、それ以外の自動 wrap なし)。
          whiteSpace: "pre",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
