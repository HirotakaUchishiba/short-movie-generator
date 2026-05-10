import React from "react";
import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { z } from "zod";
import { RenderPlan } from "../schemas/renderPlan";
import { SceneSequence } from "../components/SceneSequence";

// Layer 3 の base composition. 全 scene を時間軸に並べ、global_parts (= filter /
// bgm / outro_card 等) を重ねる。template-specific の差分 (= youtube / instagram /
// tiktok) は将来 Phase 5 で本コンポーネントを wrap して outro 等を上書きする。
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §5.1

export const ScreenplayBaseProps = z.object({
  plan: RenderPlan,
});
export type ScreenplayBaseProps = z.infer<typeof ScreenplayBaseProps>;

const toFrames = (sec: number, fps: number) => Math.round(sec * fps);

export const ScreenplayBase: React.FC<ScreenplayBaseProps> = ({ plan }) => {
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {plan.scenes.map((scene) => {
        const fromFrame = toFrames(scene.offset_sec, fps);
        const durFrames = Math.max(1, toFrames(scene.duration_sec, fps));
        return (
          <Sequence
            key={scene.index}
            from={fromFrame}
            durationInFrames={durFrames}
          >
            <SceneSequence scene={scene} />
          </Sequence>
        );
      })}

      {/* Phase 4 以降で追加: filter_preset / bgm / intro_card / outro_card の
          PartRenderer 配置。現状は global_parts は受け取るが描画しない */}
    </AbsoluteFill>
  );
};
