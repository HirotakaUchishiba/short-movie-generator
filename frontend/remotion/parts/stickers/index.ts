// stickers parts の id → component map。
// SSOT は config/part_registry/stickers.yaml の `component` フィールドと一致させる。

import {
  ExclaimRed,
  Fire,
  QuestionMark,
  Sparkle,
  ThumbsUp,
} from "./EmojiSticker";

export {
  EmojiSticker,
  ExclaimRed,
  Fire,
  QuestionMark,
  Sparkle,
  ThumbsUp,
} from "./EmojiSticker";
export type { EmojiStickerProps } from "./EmojiSticker";

export const STICKER_COMPONENTS = {
  exclaim_red: ExclaimRed,
  question_mark: QuestionMark,
  sparkle: Sparkle,
  thumbs_up: ThumbsUp,
  fire: Fire,
} as const;

export type StickerId = keyof typeof STICKER_COMPONENTS;
