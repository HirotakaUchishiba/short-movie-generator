// TTS cost 計算 (= 履歴 median rate × 単位)。
// 履歴不足なら usd / jpy は null。credits は ElevenLabs モデル仕様情報なので
// 常に算出する。
//
// StageTTS.tsx から抽出 (= 計画書 §5-c)。

import type { CostMedianRate, Line, Scene, TtsPricing } from "./types";

export interface CostBreakdown {
  chars: number;
  credits: number;
  usd: number | null;
  jpy: number | null;
}

export const ZERO_COST: CostBreakdown = {
  chars: 0,
  credits: 0,
  usd: null,
  jpy: null,
};

export function countChars(line: Line): number {
  return (line.text ?? "").length;
}

export function lineCost(
  line: Line,
  pricing: TtsPricing,
  rate: CostMedianRate | null,
): CostBreakdown {
  const chars = countChars(line);
  const credits = chars * pricing.credit_multiplier;
  if (!rate || rate.usd_per_unit == null) {
    return { chars, credits, usd: null, jpy: null };
  }
  const usd = chars * rate.usd_per_unit;
  return { chars, credits, usd, jpy: usd * rate.jpy_per_usd };
}

export function sumCost(a: CostBreakdown, b: CostBreakdown): CostBreakdown {
  const usd =
    a.usd == null && b.usd == null ? null : (a.usd ?? 0) + (b.usd ?? 0);
  const jpy =
    a.jpy == null && b.jpy == null ? null : (a.jpy ?? 0) + (b.jpy ?? 0);
  return {
    chars: a.chars + b.chars,
    credits: a.credits + b.credits,
    usd,
    jpy,
  };
}

export function sceneCost(
  scene: Scene,
  pricing: TtsPricing,
  rate: CostMedianRate | null,
): CostBreakdown {
  return (scene.lines ?? []).reduce(
    (acc, l) => sumCost(acc, lineCost(l, pricing, rate)),
    ZERO_COST,
  );
}

export function screenplayCost(
  scenes: Scene[],
  pricing: TtsPricing,
  rate: CostMedianRate | null,
): CostBreakdown {
  return scenes.reduce(
    (acc, s) => sumCost(acc, sceneCost(s, pricing, rate)),
    ZERO_COST,
  );
}

export function formatUsd(usd: number | null, digits = 4): string {
  return usd == null ? "履歴不足" : `$${usd.toFixed(digits)}`;
}

export function formatJpy(jpy: number | null): string {
  return jpy == null ? "—" : `¥${jpy.toFixed(2)}`;
}
