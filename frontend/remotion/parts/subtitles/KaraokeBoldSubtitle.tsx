import React from "react";
import {
  AbsoluteFill,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// "karaoke_bold" subtitle part.
// TikTok 系の太字字幕。表示開始時に scale 1.1 → 1.0 へ spring で settle、
// emotion (= line.emotion) に応じてハイライト色を切り替える。
// 完全な word-level karaoke は Stage 2 から alignment を取得する Phase 5 以降で
// 実装する。本 Phase 4-A では「太字 + punch アニメーション + emotion カラー」のみ。
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.3

const EMOTION_HIGHLIGHT: Record<string, string> = {
  驚き: "#FACC15", // amber
  焦り: "#F97316", // orange
  怒り: "#EF4444", // red
  喜び: "#22C55E", // green
  満足: "#22C55E",
  落胆: "#94A3B8", // slate
  困惑: "#A855F7", // violet
  恥ずかしさ: "#F472B6", // pink
};

export type KaraokeBoldSubtitleProps = {
  text: string;
  fontSize?: number;
  baseColor?: string;
  borderColor?: string;
  borderWidth?: number;
  yFromBottom?: number;
  emotion?: string;
};

export const KaraokeBoldSubtitle: React.FC<KaraokeBoldSubtitleProps> = ({
  text,
  fontSize = 96,
  baseColor = "#FFFFFF",
  borderColor = "#000000",
  borderWidth = 8,
  yFromBottom = 950,
  emotion,
}) => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  // 出現時の punch アニメーション (= 1.1 → 1.0)。
  // Sequence 配下では frame=0 が表示開始なのでそのまま使える。
  const punch = spring({
    frame,
    fps,
    from: 1.12,
    to: 1.0,
    durationInFrames: 14,
    config: { damping: 12, mass: 0.6 },
  });
  // ffmpeg drawtext の `y` はテキスト top 起点。Remotion で同じ位置にするには
  // paddingBottom = (yFromBottom - fontSize) で justifyContent flex-end する
  // (= MinimalSubtitle と同じ算出)。
  const paddingBottom = Math.max(0, yFromBottom - fontSize);

  const color = emotion ? (EMOTION_HIGHLIGHT[emotion] ?? baseColor) : baseColor;

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
          fontWeight: 900,
          fontSize,
          color,
          WebkitTextStroke: `${borderWidth}px ${borderColor}`,
          paintOrder: "stroke fill",
          textAlign: "center",
          lineHeight: 1.15,
          // ffmpeg drawtext は自動折返ししないため Remotion 側も `pre` で揃える。
          whiteSpace: "pre",
          letterSpacing: "0.02em",
          transform: `scale(${punch})`,
          transformOrigin: "center bottom",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
