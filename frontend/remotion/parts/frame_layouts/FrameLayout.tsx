import React from "react";
import { AbsoluteFill } from "remotion";

// Frame layout (= scene 動画の framing 戦略)。
// 元動画 (= 1080x1920 縦) を別レイアウトで配置するための wrapper。
// children には OffthreadVideo 等の動画レイヤを受け取る。
//
// 注意: 現状は **single-video framing** に限定 (= split / PiP は scene schema に
// secondary video 入力が必要なため future work)。本カテゴリでは元動画の見せ方
// (= 全画面 / レターボックス / blur 背景) を切替える。
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.1

export type FrameLayoutBaseProps = {
  children: React.ReactNode;
};

// ───────────── プリセット ─────────────

// "full" = identity (= 既存挙動、children をそのまま AbsoluteFill で配置)
export const FullFrame: React.FC<FrameLayoutBaseProps> = ({ children }) => (
  <AbsoluteFill>{children}</AbsoluteFill>
);

// "letterbox_top_bottom" = 上下に黒帯。動画は中央 70% に縮小して配置。
// 字幕領域の確保や cinematic 演出に使う。
export type LetterboxProps = FrameLayoutBaseProps & {
  // 動画の縦サイズ比率 (= 0-1、既定 0.7 → 上下 15% ずつ黒帯)
  videoHeightRatio?: number;
  // 黒帯の色 (= 既定 #000)
  barColor?: string;
};

export const LetterboxTopBottom: React.FC<LetterboxProps> = ({
  children,
  videoHeightRatio = 0.7,
  barColor = "#000000",
}) => {
  const heightPct = Math.max(0.3, Math.min(1, videoHeightRatio)) * 100;
  return (
    <AbsoluteFill style={{ background: barColor }}>
      <AbsoluteFill
        style={{
          top: `${(100 - heightPct) / 2}%`,
          height: `${heightPct}%`,
        }}
      >
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// "centered_with_blur" = 中央 70% に縮小した動画 + 背景は同じ動画の blur 拡大版。
// 「縦動画を 16:9 に転用するときの背景埋め」と同じ手法。
// 注意: 同じ children を 2 回 render するため、video element が 2 つ作られる。
// children は React tree のため React は同じ video URL でも別 instance になる。
export type CenteredWithBlurProps = LetterboxProps & {
  blurAmount?: number; // px、既定 40
  blurOpacity?: number; // 0-1、既定 0.6
};

export const CenteredWithBlur: React.FC<CenteredWithBlurProps> = ({
  children,
  videoHeightRatio = 0.7,
  blurAmount = 40,
  blurOpacity = 0.6,
}) => {
  const heightPct = Math.max(0.3, Math.min(1, videoHeightRatio)) * 100;
  return (
    <AbsoluteFill style={{ background: "#000000" }}>
      {/* 背景: 同じ children を blur + scale で全画面に被せる */}
      <AbsoluteFill
        style={{
          filter: `blur(${blurAmount}px)`,
          transform: "scale(1.2)",
          opacity: blurOpacity,
        }}
      >
        {children}
      </AbsoluteFill>
      {/* foreground: 縮小して中央配置 */}
      <AbsoluteFill
        style={{
          top: `${(100 - heightPct) / 2}%`,
          height: `${heightPct}%`,
        }}
      >
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
