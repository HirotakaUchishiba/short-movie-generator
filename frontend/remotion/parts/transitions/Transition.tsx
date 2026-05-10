import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

// Transition (= scene 境界に被せる effect)。
// scene_parts.transition_in (= 開始時) / transition_out (= 終了時) として
// SceneSequence が「scene 内の最初の N frame」「最後の N frame」に Sequence で
// 配置する想定。本コンポーネントは AbsoluteFill 内で frame=0 から durationInFrames
// までの progress に応じて全画面オーバーレイを描く。
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.1
//
// 実装の不変条件:
// - scene 動画自体は変更しない (= overlay を被せるだけ)
// - 親 Sequence の durationInFrames が transition の長さ
// - direction "in" は不透明 → 透明 (= 画面が現れる)
//   direction "out" は透明 → 不透明 (= 画面が消える)

export type TransitionDirection = "in" | "out";

export type DipTransitionProps = {
  direction?: TransitionDirection;
  // dip 色 (例: #000 = dip_to_black、#FFF = dip_to_white)
  color?: string;
  // 親 Sequence durationInFrames を渡す (= 開始/終了 frame の基準)
  totalFrames?: number;
};

const DipBase: React.FC<DipTransitionProps> = ({
  direction = "in",
  color = "#000000",
  totalFrames,
}) => {
  const frame = useCurrentFrame();
  const total = Math.max(1, totalFrames ?? 30);
  // direction "in" は frame 0 で opaque、frame total で transparent。
  // direction "out" は逆。
  const opacity =
    direction === "in"
      ? interpolate(frame, [0, total], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : interpolate(frame, [0, total], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
  return (
    <AbsoluteFill
      style={{
        background: color,
        opacity,
        pointerEvents: "none",
      }}
    />
  );
};

export const DipToBlack: React.FC<Omit<DipTransitionProps, "color">> = (
  props,
) => <DipBase {...props} color="#000000" />;

export const DipToWhite: React.FC<Omit<DipTransitionProps, "color">> = (
  props,
) => <DipBase {...props} color="#FFFFFF" />;

// "cut" = 何もしない identity transition (= scene 境界が hard cut で切れる)。
// 明示的に「cut にしたい」と書きたいときの用 + 既定値の代替。
export const Cut: React.FC<DipTransitionProps> = () => null;

// "fade_quick" = 短時間の不透明黒 + 短時間の不透明白の連続ではなく、薄い黒の
// quick fade (= dip 半分の濃さで素早く)。subtle な視覚区切り用。
export const FadeQuick: React.FC<DipTransitionProps> = ({
  direction = "in",
  totalFrames,
}) => {
  const frame = useCurrentFrame();
  const total = Math.max(1, totalFrames ?? 12);
  const peak = 0.35; // 半透明黒のピーク
  const opacity =
    direction === "in"
      ? interpolate(frame, [0, total], [peak, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : interpolate(frame, [0, total], [0, peak], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
  return (
    <AbsoluteFill
      style={{
        background: "#000000",
        opacity,
        pointerEvents: "none",
      }}
    />
  );
};
