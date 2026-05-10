// subtitle parts の id → component map。
// SSOT は config/part_registry/subtitle_styles.yaml の `component` フィールドと一致させる。

import { FadeInSubtitle } from "./FadeInSubtitle";
import { KaraokeBoldSubtitle } from "./KaraokeBoldSubtitle";
import { MinimalSubtitle } from "./MinimalSubtitle";

export { FadeInSubtitle } from "./FadeInSubtitle";
export { KaraokeBoldSubtitle } from "./KaraokeBoldSubtitle";
export { MinimalSubtitle } from "./MinimalSubtitle";
export type { FadeInSubtitleProps } from "./FadeInSubtitle";
export type { KaraokeBoldSubtitleProps } from "./KaraokeBoldSubtitle";
export type { MinimalSubtitleProps } from "./MinimalSubtitle";

export const SUBTITLE_COMPONENTS = {
  minimal: MinimalSubtitle,
  fade_in: FadeInSubtitle,
  karaoke_bold: KaraokeBoldSubtitle,
} as const;

export type SubtitleStyleId = keyof typeof SUBTITLE_COMPONENTS;
