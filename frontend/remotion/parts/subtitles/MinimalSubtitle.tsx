import React from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";

// "minimal" subtitle part.
// 既存 ffmpeg compositor (compositor.py) の drawtext と同等の見た目を Remotion で再現する。
// アニメーションなし、白文字 + 黒縁取り、画面下端から固定 Y 位置。
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.3

export type MinimalSubtitleProps = {
  text: string;
  fontSize?: number;
  fontColor?: string;
  borderColor?: string;
  borderWidth?: number;
  // 画面下端からの px 位置。compositor_remotion.py は screenplay の
  // subtitle_y_from_bottom 経由でこれを上書きする。
  yFromBottom?: number;
  // 折り返しの最大幅 (= 画面幅に対する比率、0-1)。
  maxWidthRatio?: number;
  // emotion ラベル (= 将来 emotion 別カラー化する際の hook、minimal では無視)
  emotion?: string;
};

export const MinimalSubtitle: React.FC<MinimalSubtitleProps> = ({
  text,
  fontSize = 76,
  fontColor = "#FFFFFF",
  borderColor = "#000000",
  borderWidth = 6,
  yFromBottom = 950,
  maxWidthRatio = 0.9,
}) => {
  const { height, width } = useVideoConfig();
  // ffmpeg drawtext は中心を y にする慣例なので、Remotion 側でも字幕中心が
  // yFromBottom に来るよう paddingBottom を fontSize/2 引いて調整する。
  const paddingBottom = Math.max(0, yFromBottom - fontSize / 2);
  const maxWidth = width * maxWidthRatio;

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          fontFamily:
            "'ヒラギノ角ゴシック W7', 'Hiragino Sans', 'Yu Gothic', sans-serif",
          fontWeight: 700,
          fontSize,
          color: fontColor,
          // CSS text-stroke で縁取り。Chromium が描く順序を fill より stroke を
          // 先にすることで文字内側まで黒が侵食しない (= ffmpeg drawtext の
          // borderw と同等の見た目)。
          WebkitTextStroke: `${borderWidth}px ${borderColor}`,
          paintOrder: "stroke fill",
          textAlign: "center",
          lineHeight: 1.2,
          maxWidth,
          // 改行は \n 受入。ffmpeg drawtext と同じ慣習。
          whiteSpace: "pre-wrap",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
