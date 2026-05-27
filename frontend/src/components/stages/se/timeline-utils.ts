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

export interface TimelineBlock {
  start: number;
  end: number;
  label: string;
}

export interface SceneLike {
  duration?: number;
  label?: string;
  lines?: { text?: string; start?: number; end?: number }[];
}

// scene を絶対秒の連続ブロックに (= 映像トラック)。offsets (実尺累積) があれば
// それを scene 開始秒に使い、無ければ duration 累積で近似する。
export function computeSceneBlocks(
  scenes: SceneLike[],
  offsets?: number[],
): TimelineBlock[] {
  const out: TimelineBlock[] = [];
  let acc = 0;
  scenes.forEach((sc, i) => {
    const dur = sc.duration ?? 0;
    const start = offsets?.[i] ?? acc;
    const end = offsets?.[i + 1] ?? start + dur;
    out.push({
      start: round3(start),
      end: round3(end),
      label: sc.label ?? `S${i + 1}`,
    });
    acc += dur;
  });
  return out;
}

// 各 line を絶対秒ブロックに (= 字幕トラック)。scene 開始秒 (offsets or 近似) +
// line の相対秒 (TTS char_ts 由来) で配置する。
export function computeSubtitleBlocks(
  scenes: SceneLike[],
  offsets?: number[],
): TimelineBlock[] {
  const out: TimelineBlock[] = [];
  let acc = 0;
  scenes.forEach((sc, i) => {
    const base = offsets?.[i] ?? acc;
    for (const line of sc.lines ?? []) {
      const s = base + (line.start ?? 0);
      const e = base + (line.end ?? line.start ?? 0);
      out.push({ start: round3(s), end: round3(e), label: line.text ?? "" });
    }
    acc += sc.duration ?? 0;
  });
  return out;
}
