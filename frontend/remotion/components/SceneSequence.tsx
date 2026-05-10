import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  staticFile,
  useVideoConfig,
} from "remotion";
import type { ResolvedScene } from "../schemas/renderPlan";
import { resolvePartComponent } from "../PartRegistry";
import { PartRenderer } from "./PartRenderer";

// 1 scene の描画責務:
//  - scene_video (= 既に lipsync 済みの scene_<S>.mp4) を full-frame
//  - subtitle_lines を chunk 単位で <Sequence> 配置
//  - scene_parts.* の各 Layer 2 パーツを必要なら overlay
//
// 不変条件:
//  - 字幕の chunk タイミングは **すでに backend (= compositor_remotion.py) で解決済み**
//    の絶対秒。Remotion 側で再計算しない (= SSOT は Python 側)
//  - scene_video_path は staticFile() で解決可能な相対パス、または http(s):// 絶対 URL

export type SceneSequenceProps = {
  scene: ResolvedScene;
};

const toFrames = (sec: number, fps: number) => Math.round(sec * fps);

const resolveSrc = (videoSrc: string): string => {
  if (/^https?:\/\//.test(videoSrc)) return videoSrc;
  return staticFile(videoSrc);
};

// snake_case key (= yaml / Python から来る) を camelCase に変換 (= React props 流儀)。
// 値は再帰せず top-level のみ。Phase 4-D で camera_move の from_scale → fromScale 等。
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

export const SceneSequence: React.FC<SceneSequenceProps> = ({ scene }) => {
  const { fps } = useVideoConfig();
  const subtitleStyle = scene.parts.subtitle_style;

  // Phase 4-D: camera_move があれば動画レイヤだけ wrap (= overlays には影響させない)。
  // params は snake_case (= yaml 流儀) で来るので React props (= camelCase) に変換。
  const cameraMoveId = scene.parts.camera_move?.id;
  const cameraParams = scene.parts.camera_move?.params ?? {};
  const cameraReactProps = camelizeParams(cameraParams);
  const CameraMoveCmp = cameraMoveId
    ? resolvePartComponent("camera_moves", cameraMoveId)
    : null;
  const videoNode = <OffthreadVideo src={resolveSrc(scene.scene_video_path)} />;
  const wrappedVideo = CameraMoveCmp ? (
    <CameraMoveCmp {...cameraReactProps}>{videoNode}</CameraMoveCmp>
  ) : (
    videoNode
  );

  return (
    <AbsoluteFill>
      {wrappedVideo}

      {/* 字幕レイヤ。各 chunk を <Sequence from={..} durationInFrames={..}> で配置。
          start/end は plan が「絶対秒」で持っているため、scene 内相対秒に直してから
          frame に変換する (= scene の Sequence 内では from=0 が scene の頭)。 */}
      {scene.subtitle_lines.flatMap((line) =>
        line.chunks.map((chunk, cIdx) => {
          const relStart = chunk.start_abs_sec - scene.offset_sec;
          const relEnd = chunk.end_abs_sec - scene.offset_sec;
          const fromFrame = Math.max(0, toFrames(relStart, fps));
          const durFrames = Math.max(1, toFrames(relEnd - relStart, fps));
          return (
            <Sequence
              key={`${line.line_idx}-${cIdx}`}
              from={fromFrame}
              durationInFrames={durFrames}
            >
              <PartRenderer
                category="subtitle_styles"
                id={subtitleStyle.id}
                params={{
                  text: chunk.text,
                  emotion: line.emotion,
                  ...(subtitleStyle.params ?? {}),
                }}
              />
            </Sequence>
          );
        }),
      )}

      {/* sticker レイヤ。`at` は scene 内相対秒 (= 0 が scene 頭)。
          duration 既定 1.5 秒。z-index は字幕の上に来る (= 字幕より後に DOM 追加)。
          詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.1 */}
      {(scene.parts.stickers ?? []).map((s, i) => {
        const fromFrame = Math.max(0, toFrames(s.at, fps));
        const durFrames = Math.max(1, toFrames(s.duration ?? 1.5, fps));
        return (
          <Sequence
            key={`sticker-${i}`}
            from={fromFrame}
            durationInFrames={durFrames}
          >
            <PartRenderer category="stickers" id={s.id} params={s.params} />
          </Sequence>
        );
      })}

      {/* lower_third レイヤ (= 名前バナー / 役職テロップ / 引用)。
          `at` は scene 内相対秒、`duration` 必須。totalFrames を child component に
          渡して exit fade のタイミングを Sequence と整合させる。
          詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.1 */}
      {scene.parts.lower_third &&
        (() => {
          const lt = scene.parts.lower_third;
          const fromFrame = Math.max(0, toFrames(lt.at, fps));
          const durFrames = Math.max(1, toFrames(lt.duration, fps));
          // params は snake_case (= yaml/Python) で来るので React props に変換
          const reactParams = camelizeParams(lt.params);
          return (
            <Sequence
              key="lower-third"
              from={fromFrame}
              durationInFrames={durFrames}
            >
              <PartRenderer
                category="lower_thirds"
                id={lt.id}
                params={{ ...reactParams, totalFrames: durFrames }}
              />
            </Sequence>
          );
        })()}
    </AbsoluteFill>
  );
};
