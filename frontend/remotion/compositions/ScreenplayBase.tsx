import React from "react";
import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { z } from "zod";
import { RenderPlan } from "../schemas/renderPlan";
import { SceneSequence } from "../components/SceneSequence";
import { resolvePartComponent } from "../PartRegistry";

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

const SceneStack: React.FC<{ plan: z.infer<typeof RenderPlan> }> = ({
  plan,
}) => {
  const { fps } = useVideoConfig();
  return (
    <>
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
    </>
  );
};

export const ScreenplayBase: React.FC<ScreenplayBaseProps> = ({ plan }) => {
  // Phase 4-C: filter_preset を screenplay 全体に被せる。
  // PART_REGISTRY 経由 dispatch なので id が見つからなければ throw (= validator が
  // 事前に reject すべきだが、defensive に実行時もチェック)。"none" は識別子として
  // 受け付け、children をそのまま返す薄い wrapper。
  const filterId = plan.global_parts.filter_preset?.id;
  const FilterCmp = filterId
    ? resolvePartComponent("filter_presets", filterId)
    : null;

  const sceneStack = <SceneStack plan={plan} />;
  const wrapped = FilterCmp ? <FilterCmp>{sceneStack}</FilterCmp> : sceneStack;

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {wrapped}

      {/* Phase 5 以降で追加: bgm / intro_card / outro_card の PartRenderer 配置 */}
    </AbsoluteFill>
  );
};
