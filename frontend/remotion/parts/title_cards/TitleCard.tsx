import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// Title card (= screenplay 全体の冒頭 (intro_card) / 末尾 (outro_card) に被せる
// 全画面カバー)。背景色 + 中央テキスト + spring fade-in + linear fade-out。
//
// 不変条件:
//  - global_parts.intro_card は plan の先頭 N frame、outro_card は末尾 N frame に
//    Sequence で配置される (= ScreenplayBase 側責務)
//  - ScreenplayBase が totalFrames を child に渡し、exit fade のタイミングを揃える
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.1, §5.1

export type TitleCardBaseProps = {
  text: string;
  subText?: string;
  // 全体長 (= 親 Sequence durationInFrames)。fade-out の基準
  totalFrames?: number;
  // 入場 spring の長さ
  enterFrames?: number;
  // 退場 fade の長さ (= total の末尾から)
  exitFrames?: number;
  // 背景色
  background?: string;
  color?: string;
};

const Base: React.FC<TitleCardBaseProps & { style?: React.CSSProperties }> = ({
  text,
  subText,
  totalFrames,
  enterFrames = 14,
  exitFrames = 10,
  background = "rgba(0,0,0,0.85)",
  color = "#FFFFFF",
  style,
}) => {
  const { fps, durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();
  const total = Math.max(1, totalFrames ?? durationInFrames);
  const enter = spring({
    frame,
    fps,
    from: 0,
    to: 1,
    durationInFrames: enterFrames,
    config: { damping: 14, mass: 0.7 },
  });
  const exit = interpolate(
    frame,
    [Math.max(0, total - exitFrames), total],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const opacity = Math.min(enter, exit);
  // 入場で text を 8% 上から下にスライドしながら opacity 0→1
  const yOffset = (1 - enter) * -32;

  return (
    <AbsoluteFill
      style={{
        background,
        color,
        opacity,
        justifyContent: "center",
        alignItems: "center",
        fontFamily:
          "'ヒラギノ角ゴシック W7', 'Hiragino Sans', 'Yu Gothic', sans-serif",
        pointerEvents: "none",
        ...style,
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 24,
          transform: `translateY(${yOffset}px)`,
          maxWidth: "84%",
          textAlign: "center",
        }}
      >
        <div style={{ fontSize: 96, fontWeight: 900, lineHeight: 1.1 }}>
          {text}
        </div>
        {subText && (
          <div
            style={{
              fontSize: 48,
              fontWeight: 500,
              lineHeight: 1.15,
              opacity: 0.85,
            }}
          >
            {subText}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};

// ───────────── プリセット ─────────────

// 黒背景 + 白文字。汎用 intro。
export const SimpleIntro: React.FC<TitleCardBaseProps> = (props) => (
  <Base {...props} background="rgba(0,0,0,0.92)" />
);

// 黒背景 + チャンネル登録誘導 (= 文言は params.text で外から)。
// YouTube outro テンプレ用。
export const SubscribeOutro: React.FC<TitleCardBaseProps> = (props) => (
  <Base
    {...props}
    background="rgba(220, 38, 38, 0.88)"
    color="#FFFFFF"
    style={{ letterSpacing: "0.02em" }}
  />
);

// シンプルな仕切り (= section 切替の "Part 2" 等)
export const SectionBreak: React.FC<TitleCardBaseProps> = (props) => (
  <Base
    {...props}
    background="rgba(15, 23, 42, 0.96)"
    style={{
      borderTop: "4px solid #38BDF8",
      borderBottom: "4px solid #38BDF8",
    }}
  />
);
