import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// Lower third (= 画面下 1/3 のテロップ。話者名 / 役職 / 引用 など)。
// 共通 base + 3 preset (= NameBanner / RoleCaption / QuoteBox)。
// 出現は左から slide-in (= spring)、消える時はゆるく fade-out。
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.1, §4.3

export type LowerThirdBaseProps = {
  // メイン text (= 名前 / 役職 / 引用文)
  text: string;
  // sub text (= 任意、二行目)
  subText?: string;
  // 画面下端からの px (1080x1920 想定)
  yFromBottom?: number;
  // 背景色 (= rgba 推奨で半透明)
  background?: string;
  // 文字色
  color?: string;
  // 出現スライド方向 (= 既定 "left" 由来 = 左から入る)
  slideFrom?: "left" | "right";
  // 出現アニメーション frame 数
  enterFrames?: number;
  // 消失 fade frame 数 (Sequence 末尾から)
  exitFrames?: number;
  // <Sequence> 全体長 (= 親 Sequence durationInFrames を渡す。
  //  渡さなければ useVideoConfig().durationInFrames を使う)
  totalFrames?: number;
};

const Base: React.FC<
  LowerThirdBaseProps & {
    // visual 差別化のための追加 children (= 左の細いアクセント色帯など)
    accent?: React.ReactNode;
    // 文字スタイルの bold / italic 等を上書き
    style?: React.CSSProperties;
  }
> = ({
  text,
  subText,
  yFromBottom = 320,
  background = "rgba(15, 23, 42, 0.82)",
  color = "#FFFFFF",
  slideFrom = "left",
  enterFrames = 12,
  exitFrames = 8,
  totalFrames,
  accent,
  style,
}) => {
  const { fps, durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();
  const total = Math.max(1, totalFrames ?? durationInFrames);
  // 入る spring: 0..1
  const enter = spring({
    frame,
    fps,
    from: 0,
    to: 1,
    durationInFrames: enterFrames,
    config: { damping: 14, mass: 0.7 },
  });
  // 出る fade: total-exitFrames..total を 1..0 に
  const exit = interpolate(
    frame,
    [Math.max(0, total - exitFrames), total],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const opacity = Math.min(enter, exit);
  const slideX = slideFrom === "left" ? (1 - enter) * -40 : (1 - enter) * 40;

  return (
    <AbsoluteFill style={{ pointerEvents: "none", justifyContent: "flex-end" }}>
      <div
        style={{
          marginBottom: yFromBottom,
          marginLeft: 56,
          marginRight: 56,
          background,
          color,
          padding: "20px 28px",
          borderRadius: 10,
          display: "flex",
          alignItems: "center",
          gap: 16,
          opacity,
          transform: `translateX(${slideX}px)`,
          fontFamily:
            "'ヒラギノ角ゴシック W7', 'Hiragino Sans', 'Yu Gothic', sans-serif",
          ...style,
        }}
      >
        {accent}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 56, fontWeight: 800, lineHeight: 1.1 }}>
            {text}
          </div>
          {subText && (
            <div
              style={{
                fontSize: 32,
                fontWeight: 500,
                lineHeight: 1.1,
                opacity: 0.85,
              }}
            >
              {subText}
            </div>
          )}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ───────────── プリセット ─────────────

export const NameBanner: React.FC<LowerThirdBaseProps> = (props) => (
  <Base
    {...props}
    background="rgba(15, 23, 42, 0.86)"
    accent={
      <div
        style={{
          width: 6,
          alignSelf: "stretch",
          background: "#38BDF8",
          borderRadius: 3,
        }}
      />
    }
  />
);

export const RoleCaption: React.FC<LowerThirdBaseProps> = (props) => (
  <Base
    {...props}
    background="rgba(20, 83, 45, 0.86)"
    accent={
      <div
        style={{
          width: 6,
          alignSelf: "stretch",
          background: "#FACC15",
          borderRadius: 3,
        }}
      />
    }
  />
);

export const QuoteBox: React.FC<LowerThirdBaseProps> = ({
  text,
  subText,
  ...rest
}) => (
  <Base
    {...rest}
    text={`“${text}”`}
    subText={subText}
    background="rgba(67, 56, 202, 0.78)"
    style={{ fontStyle: "italic" }}
  />
);
