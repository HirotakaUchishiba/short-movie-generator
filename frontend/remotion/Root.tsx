import { Composition } from "remotion";
import { HelloWorld, HelloWorldProps } from "./compositions/HelloWorld";
import {
  ScreenplayBase,
  ScreenplayBaseProps,
} from "./compositions/ScreenplayBase";

// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §5

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Phase 0: minimum viable Hello World (= 1 シーン + 1 字幕の smoke test) */}
      <Composition
        id="HelloWorld"
        component={HelloWorld}
        durationInFrames={60 * 8}
        fps={60}
        width={1080}
        height={1920}
        schema={HelloWorldProps}
        defaultProps={{
          videoSrc: "https://example.com/placeholder.mp4",
          subtitleText: "Hello, Remotion!",
          subtitleStart: 0.5,
          subtitleEnd: 2.5,
        }}
      />

      {/* Phase 2-A: 本番用 base composition (= RenderPlan を受けて全 scene をレンダ)。
          実際の durationInFrames / fps / 解像度は plan.video.* で起動時に上書きする
          (= async calculateMetadata で props 由来の値を返す) */}
      <Composition
        id="ScreenplayBase"
        component={ScreenplayBase}
        // defaultProps の duration を低くしておくと calculateMetadata が効かない環境で
        // フォールバックされた時に短すぎてバレる。十分長い既定値を置く
        durationInFrames={60 * 600}
        fps={60}
        width={1080}
        height={1920}
        schema={ScreenplayBaseProps}
        calculateMetadata={async ({ props }) => {
          const v = props.plan.video;
          return {
            durationInFrames: v.duration_frames,
            fps: v.fps,
            width: v.width,
            height: v.height,
          };
        }}
        defaultProps={{
          plan: {
            video: {
              width: 1080,
              height: 1920,
              fps: 60,
              duration_frames: 60 * 600,
            },
            scenes: [],
            global_parts: {},
            template: "base" as const,
          },
        }}
      />
    </>
  );
};
