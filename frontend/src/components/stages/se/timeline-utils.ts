// SE タイムライン UI の純粋ロジック (wavesurfer DOM から切り離してテスト可能にする)。
// SeItem[] (= 時刻ベース) と波形上の region (= start/end) を相互変換する。
import type { SeItem, SeTrack } from "../../../types";

export interface SeRegion {
  idx: number;
  start: number;
  end: number;
  seId: string;
}

// duration 不明 (catalog に無い / 0) の SE は最小幅で描く (= クリック可能にする)。
const MIN_REGION_WIDTH = 0.3;

function round3(n: number): number {
  return Math.round(n * 1000) / 1000;
}

export function itemsToRegions(items: SeItem[], tracks: SeTrack[]): SeRegion[] {
  const durById = new Map(tracks.map((t) => [t.id, t.duration_sec ?? 0]));
  return items.map((it, idx) => {
    const dur = durById.get(it.se_id) ?? 0;
    const width = dur > 0 ? dur : MIN_REGION_WIDTH;
    return {
      idx,
      start: it.time,
      end: round3(it.time + width),
      seId: it.se_id,
    };
  });
}

export function moveItemTime(
  items: SeItem[],
  idx: number,
  newTime: number,
): SeItem[] {
  const t = round3(Math.max(0, newTime));
  return items.map((it, i) => (i === idx ? { ...it, time: t } : it));
}

export function addItemAt(
  items: SeItem[],
  time: number,
  seId: string,
  volume: number,
): SeItem[] {
  return [
    ...items,
    {
      time: round3(Math.max(0, time)),
      se_id: seId,
      volume,
      source: "manual",
      reason: "",
    },
  ];
}

export function removeItemAt(items: SeItem[], idx: number): SeItem[] {
  return items.filter((_, i) => i !== idx);
}
