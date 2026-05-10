// filter_presets parts の id → component map。
// SSOT は config/part_registry/filter_presets.yaml の `component` フィールドと一致させる。

import {
  CoolBlue,
  Monochrome,
  NoneFilter,
  Vintage,
  WarmCinematic,
} from "./FilterWrapper";

export {
  CoolBlue,
  FilterWrapper,
  Monochrome,
  NoneFilter,
  Vintage,
  WarmCinematic,
} from "./FilterWrapper";
export type { FilterWrapperProps } from "./FilterWrapper";

export const FILTER_PRESET_COMPONENTS = {
  none: NoneFilter,
  warm_cinematic: WarmCinematic,
  cool_blue: CoolBlue,
  monochrome: Monochrome,
  vintage: Vintage,
} as const;

export type FilterPresetId = keyof typeof FILTER_PRESET_COMPONENTS;
