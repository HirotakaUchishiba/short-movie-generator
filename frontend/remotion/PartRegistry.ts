// Layer 2 (compositional parts) の id → React component dispatch table.
// SSOT は config/part_registry/<category>.yaml + 各 parts/<category>/index.ts。
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.3, §5.2

import { CAMERA_MOVE_COMPONENTS } from "./parts/camera_moves";
import { FILTER_PRESET_COMPONENTS } from "./parts/filter_presets";
import { LOWER_THIRD_COMPONENTS } from "./parts/lower_thirds";
import { STICKER_COMPONENTS } from "./parts/stickers";
import { SUBTITLE_COMPONENTS } from "./parts/subtitles";

export const PART_REGISTRY = {
  subtitle_styles: SUBTITLE_COMPONENTS,
  stickers: STICKER_COMPONENTS,
  filter_presets: FILTER_PRESET_COMPONENTS,
  camera_moves: CAMERA_MOVE_COMPONENTS,
  lower_thirds: LOWER_THIRD_COMPONENTS,
  // 将来追加:
  //   transitions: TRANSITION_COMPONENTS,
  //   title_cards: TITLE_CARD_COMPONENTS,
  //   frame_layouts: FRAME_LAYOUT_COMPONENTS,
} as const;

export type PartCategory = keyof typeof PART_REGISTRY;

export function resolvePartComponent(
  category: PartCategory,
  id: string,
): React.ComponentType<any> {
  const cat = PART_REGISTRY[category] as Record<
    string,
    React.ComponentType<any>
  >;
  const cmp = cat[id];
  if (!cmp) {
    throw new Error(
      `unknown part: category=${category} id=${id}. ` +
        `Add it to config/part_registry/${category}.yaml + ` +
        `frontend/remotion/parts/${category}/index.ts`,
    );
  }
  return cmp;
}

export function isKnownPart(category: string, id: string): boolean {
  if (!(category in PART_REGISTRY)) return false;
  const cat = PART_REGISTRY[category as PartCategory] as Record<
    string,
    unknown
  >;
  return id in cat;
}
