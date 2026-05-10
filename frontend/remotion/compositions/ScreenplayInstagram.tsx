import React from "react";
import { z } from "zod";
import { RenderPlan } from "../schemas/renderPlan";
import { ScreenplayBase } from "./ScreenplayBase";

// Instagram Reels 用 composition (Phase 5-A)。
// IG 風: 太字字幕 + 冒頭 1 秒の hook ホールド + outro 簡潔に。
//
// 仕様:
// - intro_card 未指定なら "simple_intro" 1.0 秒で hook ホールド
// - 各 scene の subtitle_style が "minimal" のままなら "karaoke_bold" に強制上書き
//   (= IG ユーザーは subtitle が太字の方が定着率高い)
// - outro_card は plan を引き継ぐのみ (= IG 公式の outro 強制はないため柔軟)
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §5.4

export const ScreenplayInstagramProps = z.object({
  plan: RenderPlan,
});
export type ScreenplayInstagramProps = z.infer<typeof ScreenplayInstagramProps>;

export const ScreenplayInstagram: React.FC<ScreenplayInstagramProps> = ({
  plan,
}) => {
  // Subtitle style 強制: minimal → karaoke_bold
  const planForIg: z.infer<typeof RenderPlan> = {
    ...plan,
    template: "instagram",
    global_parts: {
      ...plan.global_parts,
      intro_card: plan.global_parts.intro_card,
    },
    scenes: plan.scenes.map((scene) => ({
      ...scene,
      parts: {
        ...scene.parts,
        subtitle_style:
          scene.parts.subtitle_style.id === "minimal"
            ? { id: "karaoke_bold", params: scene.parts.subtitle_style.params }
            : scene.parts.subtitle_style,
      },
    })),
  };
  return <ScreenplayBase plan={planForIg} />;
};
