// transitions parts の id → component map。
// SSOT は config/part_registry/transitions.yaml の `component` フィールドと一致させる。

import { Cut, DipToBlack, DipToWhite, FadeQuick } from "./Transition";

export { Cut, DipToBlack, DipToWhite, FadeQuick } from "./Transition";
export type { DipTransitionProps, TransitionDirection } from "./Transition";

export const TRANSITION_COMPONENTS = {
  cut: Cut,
  dip_to_black: DipToBlack,
  dip_to_white: DipToWhite,
  fade_quick: FadeQuick,
} as const;

export type TransitionId = keyof typeof TRANSITION_COMPONENTS;
