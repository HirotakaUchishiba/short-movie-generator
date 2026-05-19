// StageTTS.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 現在のモデル / 文字数 / コスト / 速度 / 無音圧縮設定をまとめて表示する
// バナー。ModelSelector / SpeedControl / SilenceControl を内包する。

import type { TtsPricing } from "../../types";
import { type CostBreakdown, formatJpy, formatUsd } from "../../tts-cost";
import { ModelSelector, SilenceControl, SpeedControl } from "./TtsControls";
import { modelMeta } from "./tts-utils";

// 単純な label / value 縦並び。PricingBanner 内の各統計表示で使う。
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-semibold">{value}</div>
    </div>
  );
}

export function PricingBanner({
  pricing,
  totalCost,
}: {
  pricing: TtsPricing;
  totalCost: CostBreakdown;
}) {
  const meta = modelMeta(pricing.model);
  return (
    <div className="card border-emerald-700/40 bg-emerald-900/10">
      <div className="flex flex-wrap items-stretch gap-4">
        <div
          className={`rounded-md border px-4 py-3 flex flex-col justify-center min-w-[280px] ${meta.color}`}
        >
          <div className="text-[10px] uppercase tracking-wider opacity-70">
            使用中のモデル
          </div>
          <ModelSelector pricing={pricing} />
          <div className="flex gap-2 mt-1.5 text-[11px]">
            <span className="badge bg-black/30">
              文字単価 ×{pricing.credit_multiplier}
            </span>
            <span className="badge bg-black/30">{meta.contextLabel}</span>
            <span className="badge bg-black/30">{meta.qualityLabel}</span>
          </div>
        </div>
        <div className="flex-1 flex items-center justify-end gap-4 flex-wrap">
          <Stat label="全文字数" value={`${totalCost.chars} 字`} />
          <Stat
            label="credits"
            value={`${totalCost.credits.toLocaleString()}`}
          />
          <Stat label="全シーン1回生成" value={formatUsd(totalCost.usd, 3)} />
          <Stat label="(円換算)" value={formatJpy(totalCost.jpy)} />
        </div>
      </div>
      <SpeedControl key={pricing.global_speed} pricing={pricing} />
      <SilenceControl
        key={`${pricing.trim_silences}|${pricing.max_silence_ms}`}
        pricing={pricing}
      />
    </div>
  );
}
