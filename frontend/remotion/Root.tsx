import { Composition } from "remotion";
import { HelloWorld, HelloWorldProps } from "./compositions/HelloWorld";

// Phase 0: minimum viable Composition の registerRoot。
// Phase 2 以降で ScreenplayBase / Screenplay{Youtube,Instagram,TikTok} 等を追加する。

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="HelloWorld"
        component={HelloWorld}
        durationInFrames={60 * 8} // 8 秒 @ 60fps
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
    </>
  );
};
