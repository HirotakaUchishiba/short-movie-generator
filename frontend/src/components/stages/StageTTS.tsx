import { useMemo } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { useCostMedianRate } from "../../useCostMedianRate";
import { screenplayCost } from "../../tts-cost";
import { BulkRegenBar } from "./BulkRegenBar";
import { MergedTTSPlayer } from "./MergedTTSPlayer";
import { PricingBanner } from "./PricingBanner";
import { SceneTTSCard } from "./SceneTTSCard";
import { TtsSourcePreview } from "./TtsSourcePreview";
// 各 sub-component は ./{BulkRegenBar / MergedTTSPlayer / PricingBanner /
// SceneTTSCard / TtsSourcePreview / TtsControls / MergedTTSPlayer}.tsx に
// 移管済 (= §3.1.3)。modelMeta は ./tts-utils.ts。
// コスト計算 (= lineCost / sceneCost / screenplayCost / formatUsd / formatJpy)
// は ../../tts-cost.ts に抽出済み (= §5-c)。
// シーン境界編集は Stage 1 (ScriptEditPanel) に移動済み。Stage 2 では扱わない。

export default function StageTTS() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const { rate } = useCostMedianRate("tts", ctx.serverConfig.cost_models.tts);
  const totalCost = useMemo(
    () => screenplayCost(sp.scenes, ctx.serverConfig.tts_pricing, rate),
    [sp.scenes, ctx.serverConfig.tts_pricing, rate],
  );

  return (
    <StageGate
      stage="tts"
      title="TTS音声の生成"
      description="screenplay全体を1 API call で生成。line.audio_tags があれば ElevenLabs V3 inline tag として注入。各lineの再生成は不可、全体まとめての再生成のみ。"
      needsRunFirst
    >
      <PricingBanner
        pricing={ctx.serverConfig.tts_pricing}
        totalCost={totalCost}
      />
      <TtsSourcePreview />
      <BulkRegenBar totalCost={totalCost} />
      <MergedTTSPlayer />
      <div className="space-y-6 mt-4">
        {sp.scenes.map((scene, sIdx) => (
          <SceneTTSCard
            key={scene._uid ?? sIdx}
            scene={scene}
            sIdx={sIdx}
            pricing={ctx.serverConfig.tts_pricing}
            rate={rate}
          />
        ))}
      </div>
    </StageGate>
  );
}
