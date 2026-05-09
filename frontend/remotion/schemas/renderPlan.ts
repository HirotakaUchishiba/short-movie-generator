import { z } from "zod";

// Layer 3 (Composition Engine) への入力スキーマ。
// Python 側 (compositor_remotion.py) が build_render_plan() で組み立て、
// このスキーマに合致した JSON を Remotion render に渡す。
//
// 設計の不変条件 (= 2026-05-10_compositional-architecture.md §1.3):
//  - SSOT は Python 側。Remotion は「貰った値を信じて描画するだけ」
//  - subtitle の chunk start/end は **解決済み絶対秒** (= scene offset 込み)
//  - scenes[].duration_sec は **scene_<S>.mp4 の実尺** (= ffprobe 計測値)

export const PartReference = z.object({
  id: z.string(),
  params: z.record(z.string(), z.unknown()).default({}),
});
export type PartReference = z.infer<typeof PartReference>;

export const SubtitleChunk = z.object({
  text: z.string(),
  start_abs_sec: z.number(),
  end_abs_sec: z.number(),
  anchor_kind: z.enum(["auto", "manual"]).default("auto"),
});
export type SubtitleChunk = z.infer<typeof SubtitleChunk>;

export const SubtitleLine = z.object({
  line_idx: z.number(),
  emotion: z.string().optional(),
  chunks: z.array(SubtitleChunk),
});
export type SubtitleLine = z.infer<typeof SubtitleLine>;

export const StickerPart = z.object({
  id: z.string(),
  at: z.number(),
  duration: z.number().optional(),
  params: z.record(z.string(), z.unknown()).default({}),
});
export type StickerPart = z.infer<typeof StickerPart>;

export const LowerThirdPart = z.object({
  id: z.string(),
  at: z.number(),
  duration: z.number(),
  params: z.record(z.string(), z.unknown()).default({}),
});
export type LowerThirdPart = z.infer<typeof LowerThirdPart>;

export const SfxPart = z.object({
  path: z.string(),
  at: z.number(),
  volume: z.number().optional(),
});
export type SfxPart = z.infer<typeof SfxPart>;

export const ScenePartsBundle = z.object({
  subtitle_style: PartReference,
  stickers: z.array(StickerPart).optional(),
  lower_third: LowerThirdPart.optional(),
  camera_move: PartReference.optional(),
  transition_in: PartReference.optional(),
  transition_out: PartReference.optional(),
  sfx: z.array(SfxPart).optional(),
});
export type ScenePartsBundle = z.infer<typeof ScenePartsBundle>;

export const ResolvedScene = z.object({
  index: z.number(),
  scene_video_path: z.string(),
  offset_sec: z.number(),
  duration_sec: z.number(),
  subtitle_lines: z.array(SubtitleLine),
  parts: ScenePartsBundle,
});
export type ResolvedScene = z.infer<typeof ResolvedScene>;

export const GlobalParts = z.object({
  filter_preset: PartReference.optional(),
  bgm: z
    .object({
      path: z.string(),
      ducking_curve: z.union([
        z.number(),
        z.array(z.tuple([z.number(), z.number()])),
      ]),
    })
    .optional(),
  intro_card: z
    .object({
      id: z.string(),
      duration_sec: z.number(),
      params: z.record(z.string(), z.unknown()).default({}),
    })
    .optional(),
  outro_card: z
    .object({
      id: z.string(),
      duration_sec: z.number(),
      params: z.record(z.string(), z.unknown()).default({}),
    })
    .optional(),
});
export type GlobalParts = z.infer<typeof GlobalParts>;

export const VideoMeta = z.object({
  width: z.number(),
  height: z.number(),
  fps: z.number(),
  duration_frames: z.number(),
});
export type VideoMeta = z.infer<typeof VideoMeta>;

export const RenderPlan = z.object({
  video: VideoMeta,
  scenes: z.array(ResolvedScene),
  global_parts: GlobalParts.default({}),
  template: z.enum(["base", "youtube", "instagram", "tiktok"]).default("base"),
});
export type RenderPlan = z.infer<typeof RenderPlan>;
