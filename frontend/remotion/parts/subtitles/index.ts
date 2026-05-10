// subtitle parts の id → component map。
// SSOT は config/part_registry/subtitle_styles.yaml の `component` フィールドと一致させる。

import { MinimalSubtitle } from "./MinimalSubtitle";

export { MinimalSubtitle } from "./MinimalSubtitle";
export type { MinimalSubtitleProps } from "./MinimalSubtitle";

export const SUBTITLE_COMPONENTS = {
  minimal: MinimalSubtitle,
  // Phase 2-B 以降で追加: karaoke_bold, fade_in, bouncing_word
} as const;

export type SubtitleStyleId = keyof typeof SUBTITLE_COMPONENTS;
