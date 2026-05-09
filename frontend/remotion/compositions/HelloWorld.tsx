import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  staticFile,
  useVideoConfig,
} from "remotion";
import { z } from "zod";

// Phase 0 minimum viable: 1 シーン動画 + 1 字幕を Remotion で描画する。
// 既存 ffmpeg overlay と同等の見た目を出せることを確認するための smoke test composition。

export const HelloWorldProps = z.object({
  videoSrc: z.string(),
  subtitleText: z.string().default("Hello, Remotion!"),
  subtitleStart: z.number().default(0.5),
  subtitleEnd: z.number().default(2.5),
});
export type HelloWorldProps = z.infer<typeof HelloWorldProps>;

export const HelloWorld: React.FC<HelloWorldProps> = ({
  videoSrc,
  subtitleText,
  subtitleStart,
  subtitleEnd,
}) => {
  const { fps, height } = useVideoConfig();
  const startFrame = Math.round(subtitleStart * fps);
  const durationFrames = Math.max(
    1,
    Math.round((subtitleEnd - subtitleStart) * fps),
  );

  // 既存 ffmpeg overlay と同じ Y 位置 (= config.SUBTITLE_Y_FROM_BOTTOM = 950)
  // を Remotion 側でも再現できるか確認するための仮値。
  const subtitleYFromBottom = 950;
  const subtitleBottom = subtitleYFromBottom - 38; // 字幕高さの半分 (= ~76/2) を引いた位置

  // videoSrc が http(s):// なら直接、そうでなければ staticFile() 経由で
  // public-dir からの相対パスとして解決する。
  // compositor_remotion.py は scene_<S>.mp4 を public dir 経由で配信し、
  // この composition には相対パス (= "scene_000.mp4" 等) を渡す前提。
  const resolvedSrc = /^https?:\/\//.test(videoSrc)
    ? videoSrc
    : staticFile(videoSrc);

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <OffthreadVideo src={resolvedSrc} />
      <Sequence from={startFrame} durationInFrames={durationFrames}>
        <AbsoluteFill
          style={{
            justifyContent: "flex-end",
            alignItems: "center",
            paddingBottom: subtitleBottom,
          }}
        >
          <div
            style={{
              fontFamily:
                "'ヒラギノ角ゴシック W7', 'Hiragino Sans', sans-serif",
              fontSize: 76,
              color: "#FFFFFF",
              WebkitTextStroke: "6px #000000",
              paintOrder: "stroke fill",
              textAlign: "center",
              lineHeight: 1.2,
              maxWidth: "90%",
            }}
          >
            {subtitleText}
          </div>
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};
