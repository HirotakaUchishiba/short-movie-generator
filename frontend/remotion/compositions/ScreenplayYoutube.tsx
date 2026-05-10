import React from "react";
import { z } from "zod";
import { RenderPlan } from "../schemas/renderPlan";
import { ScreenplayBase } from "./ScreenplayBase";

// YouTube Shorts 用 composition (Phase 5-A)。
// ScreenplayBase をそのまま wrap して global_parts.outro_card / subtitle_style 等の
// 既定値を YouTube 寄りに上書きする。
//
// 仕様:
// - outro_card 未指定なら "subscribe_outro" 2 秒を末尾に注入
// - subtitle_style は scene 個別指定優先、未指定なら "minimal"
// - filter_preset は引き継ぐのみ (= screenplay 指定優先)
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §5.4

export const ScreenplayYoutubeProps = z.object({
  plan: RenderPlan,
});
export type ScreenplayYoutubeProps = z.infer<typeof ScreenplayYoutubeProps>;

export const ScreenplayYoutube: React.FC<ScreenplayYoutubeProps> = ({
  plan,
}) => {
  const planForYoutube: z.infer<typeof RenderPlan> = {
    ...plan,
    template: "youtube",
    global_parts: {
      ...plan.global_parts,
      outro_card: plan.global_parts.outro_card ?? {
        id: "subscribe_outro",
        duration_sec: 2.0,
        params: {
          text: "チャンネル登録お願いします",
          sub_text: "↓ ボタンを押すだけ",
        },
      },
    },
  };
  return <ScreenplayBase plan={planForYoutube} />;
};
