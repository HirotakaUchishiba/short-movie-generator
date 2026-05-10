// lower_thirds parts の id → component map。
// SSOT は config/part_registry/lower_thirds.yaml の `component` フィールドと一致させる。

import { NameBanner, QuoteBox, RoleCaption } from "./LowerThird";

export { NameBanner, QuoteBox, RoleCaption } from "./LowerThird";
export type { LowerThirdBaseProps } from "./LowerThird";

export const LOWER_THIRD_COMPONENTS = {
  name_banner: NameBanner,
  role_caption: RoleCaption,
  quote_box: QuoteBox,
} as const;

export type LowerThirdId = keyof typeof LOWER_THIRD_COMPONENTS;
