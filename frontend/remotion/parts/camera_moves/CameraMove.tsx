import React from "react";
import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// 全 camera_move の共通 base。children (= OffthreadVideo を含むレイヤ) を
// CSS transform で wrap し、frame に応じて scale/translate を補間する。
//
// 不変条件:
//  - 元動画は変更しない (= scene_<S>.mp4 はそのまま)。Remotion が render 時に
//    transform 付きで再描画するだけ
//  - 動画の音声は transform に影響されない (= OffthreadVideo の audio track は
//    Remotion が透過して output へ流す)
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.1, §4.3

export type CameraMoveBaseProps = {
  // 動画の長さ全体に対して補間する progress (0-1) を計算する基準。
  // 既定: 入っている <Sequence> の長さ全体 (= scene 全長)
  durationFrames?: number;
  children: React.ReactNode;
};

// 0-1 progress を frame ベースで返すユーティリティ。
// SceneSequence の <Sequence> 配下では frame=0 が scene 頭。
function useProgress(durationFrames?: number): number {
  const { fps, durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();
  const total = Math.max(1, durationFrames ?? durationInFrames);
  void fps;
  return Math.min(1, frame / total);
}

// ───────────── プリセット ─────────────

export type SubtleZoomInProps = CameraMoveBaseProps & {
  // 開始 scale (= 既定 1.00) と終了 scale (= 既定 1.05)
  fromScale?: number;
  toScale?: number;
};

export const SubtleZoomIn: React.FC<SubtleZoomInProps> = ({
  fromScale = 1.0,
  toScale = 1.05,
  durationFrames,
  children,
}) => {
  const progress = useProgress(durationFrames);
  const scale = interpolate(progress, [0, 1], [fromScale, toScale]);
  return (
    <AbsoluteFill
      style={{ transform: `scale(${scale})`, transformOrigin: "center" }}
    >
      {children}
    </AbsoluteFill>
  );
};

export type KenBurnsProps = CameraMoveBaseProps & {
  // pan の振幅 (= 0-1 比率、frame の % で指定)。既定: 4% 右へドリフト
  panFromX?: number;
  panToX?: number;
  panFromY?: number;
  panToY?: number;
  fromScale?: number;
  toScale?: number;
};

export const KenBurns: React.FC<KenBurnsProps> = ({
  panFromX = 0,
  panToX = 0.04,
  panFromY = 0,
  panToY = -0.02,
  fromScale = 1.05,
  toScale = 1.12,
  durationFrames,
  children,
}) => {
  const progress = useProgress(durationFrames);
  const x = interpolate(progress, [0, 1], [panFromX, panToX]);
  const y = interpolate(progress, [0, 1], [panFromY, panToY]);
  const scale = interpolate(progress, [0, 1], [fromScale, toScale]);
  return (
    <AbsoluteFill
      style={{
        transform: `scale(${scale}) translate(${x * 100}%, ${y * 100}%)`,
        transformOrigin: "center",
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

export type DollyPullBackProps = CameraMoveBaseProps & {
  // 引き (= scale 1.10 から 1.00 に戻す) で「全体が見えてくる」感
  fromScale?: number;
  toScale?: number;
};

export const DollyPullBack: React.FC<DollyPullBackProps> = ({
  fromScale = 1.1,
  toScale = 1.0,
  durationFrames,
  children,
}) => {
  const progress = useProgress(durationFrames);
  const scale = interpolate(progress, [0, 1], [fromScale, toScale]);
  return (
    <AbsoluteFill
      style={{ transform: `scale(${scale})`, transformOrigin: "center" }}
    >
      {children}
    </AbsoluteFill>
  );
};

// "none" = identity wrapper (= camera_move を明示的に「無し」と書きたいとき用)
export const NoneCameraMove: React.FC<CameraMoveBaseProps> = ({ children }) => (
  <>{children}</>
);
