// StageKling.tsx から抽出 (= §3.1.3 helper 分離)。
//
// Kling は audio_duration を 5/10s クリップに切り上げて課金する
// (= 課金 unit 確定ロジック、単価ではない)。tolerance 1.2 倍
// = 5.0s clip で 6.0s まで吸収 (超過分は slow_mo extension)。

import type { CostMedianRate } from "../../types";

const KLING_DURATION_TOLERANCE_RATIO = 1.2;

export function klingBilledDuration(audioDurSec: number): number {
  const fiveSecMax = 5 * KLING_DURATION_TOLERANCE_RATIO;
  return audioDurSec <= fiveSecMax ? 5 : 10;
}

export function klingSceneCost(
  audioDurSec: number,
  rate: CostMedianRate | null,
): number | null {
  if (!rate || rate.usd_per_unit == null) return null;
  return klingBilledDuration(audioDurSec) * rate.usd_per_unit;
}

export function formatKlingCost(usd: number | null): string {
  return usd == null ? "履歴不足" : `$${usd.toFixed(2)}`;
}
