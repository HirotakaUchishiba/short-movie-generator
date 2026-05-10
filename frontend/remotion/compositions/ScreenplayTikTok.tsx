import React from "react";
import { z } from "zod";
import { RenderPlan } from "../schemas/renderPlan";
import { ScreenplayBase } from "./ScreenplayBase";

// TikTok 用 composition (Phase 5-A)。
// TikTok 風: karaoke_bold 字幕、字幕位置を画面下 1/3 に上げる、outro 短め。
//
// 仕様:
// - 各 scene の subtitle_style を "karaoke_bold" に強制 (= IG と同じ)
// - 字幕位置を画面下から 1/3 (= 1920 / 3 ≈ 640) にずらす
//   (= TikTok の UI は画面下端に hashtag / username が出るため字幕は上に)
// - outro_card 未指定なら "section_break" 1.0 秒で短く締める (= TikTok は
//   subscribe CTA を使うと UX 違反扱いされやすい)
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §5.4

const TIKTOK_SUBTITLE_Y = 640; // 画面下から 640px (= 約 1/3)

export const ScreenplayTikTokProps = z.object({
  plan: RenderPlan,
});
export type ScreenplayTikTokProps = z.infer<typeof ScreenplayTikTokProps>;

export const ScreenplayTikTok: React.FC<ScreenplayTikTokProps> = ({ plan }) => {
  const planForTiktok: z.infer<typeof RenderPlan> = {
    ...plan,
    template: "tiktok",
    global_parts: {
      ...plan.global_parts,
      outro_card: plan.global_parts.outro_card ?? {
        id: "section_break",
        duration_sec: 1.0,
        params: { text: "fin." },
      },
    },
    scenes: plan.scenes.map((scene) => ({
      ...scene,
      parts: {
        ...scene.parts,
        subtitle_style: {
          id: "karaoke_bold",
          // 既存 params に y_from_bottom を上書き (= TikTok 用に上げる)
          params: {
            ...(scene.parts.subtitle_style.params ?? {}),
            y_from_bottom: TIKTOK_SUBTITLE_Y,
          },
        },
      },
    })),
  };
  return <ScreenplayBase plan={planForTiktok} />;
};
