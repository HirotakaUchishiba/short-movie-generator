// frame_layouts parts の id → component map。
// SSOT は config/part_registry/frame_layouts.yaml の `component` フィールドと一致させる。

import { CenteredWithBlur, FullFrame, LetterboxTopBottom } from "./FrameLayout";

export { CenteredWithBlur, FullFrame, LetterboxTopBottom } from "./FrameLayout";
export type {
  CenteredWithBlurProps,
  FrameLayoutBaseProps,
  LetterboxProps,
} from "./FrameLayout";

export const FRAME_LAYOUT_COMPONENTS = {
  full: FullFrame,
  letterbox_top_bottom: LetterboxTopBottom,
  centered_with_blur: CenteredWithBlur,
} as const;

export type FrameLayoutId = keyof typeof FRAME_LAYOUT_COMPONENTS;
