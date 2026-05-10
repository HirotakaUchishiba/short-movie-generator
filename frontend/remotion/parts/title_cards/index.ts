// title_cards parts の id → component map。
// SSOT は config/part_registry/title_cards.yaml の `component` フィールドと一致させる。

import { SectionBreak, SimpleIntro, SubscribeOutro } from "./TitleCard";

export { SectionBreak, SimpleIntro, SubscribeOutro } from "./TitleCard";
export type { TitleCardBaseProps } from "./TitleCard";

export const TITLE_CARD_COMPONENTS = {
  simple_intro: SimpleIntro,
  subscribe_outro: SubscribeOutro,
  section_break: SectionBreak,
} as const;

export type TitleCardId = keyof typeof TITLE_CARD_COMPONENTS;
