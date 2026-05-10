import React from "react";
import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { z } from "zod";
import { RenderPlan } from "../schemas/renderPlan";
import { SceneSequence } from "../components/SceneSequence";
import { resolvePartComponent } from "../PartRegistry";

// snake_case key (= yaml / Python 流儀) を camelCase (= React props 流儀) に変換。
// 値は再帰せず top-level のみ。Phase 4-F で title_card の sub_text → subText 等。
function camelizeParams(
  params: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(params)) {
    const cc = k.replace(/_([a-z0-9])/g, (_m, c: string) => c.toUpperCase());
    out[cc] = v;
  }
  return out;
}

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

  // Phase 4-F: intro_card / outro_card は plan.video.duration_frames を境界として
  // 冒頭 / 末尾の Sequence に配置する。filter_preset の影響は受けない (= AbsoluteFill
  // の上に重ねる)。totalFrames を child に渡して exit fade を Sequence と整合させる。
  const intro = plan.global_parts.intro_card;
  const outro = plan.global_parts.outro_card;
  const fps = plan.video.fps;
  const introFrames = intro
    ? Math.max(1, Math.round(intro.duration_sec * fps))
    : 0;
  const outroFrames = outro
    ? Math.max(1, Math.round(outro.duration_sec * fps))
    : 0;
  const outroFromFrame = Math.max(0, plan.video.duration_frames - outroFrames);

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {wrapped}

      {intro && (
        <Sequence from={0} durationInFrames={introFrames}>
          {(() => {
            const Cmp = resolvePartComponent("title_cards", intro.id);
            const reactParams = camelizeParams(intro.params ?? {});
            return <Cmp {...reactParams} totalFrames={introFrames} />;
          })()}
        </Sequence>
      )}

      {outro && (
        <Sequence from={outroFromFrame} durationInFrames={outroFrames}>
          {(() => {
            const Cmp = resolvePartComponent("title_cards", outro.id);
            const reactParams = camelizeParams(outro.params ?? {});
            return <Cmp {...reactParams} totalFrames={outroFrames} />;
          })()}
        </Sequence>
      )}
    </AbsoluteFill>
  );
};
