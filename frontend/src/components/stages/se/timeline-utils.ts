// SE タイムライン UI の純粋ロジック (wavesurfer DOM から切り離してテスト可能にする)。
// SeItem[] (= 時刻ベース) と timeline 上の region (= start/end) を相互変換する。
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

// SE 音源の再生範囲 (= trim 後の長さ)。clip_start/clip_end があればそれ、無ければ
// 0〜full duration。full=0 は最小幅。
function clipWidth(it: SeItem, full: number): number {
  const cs = it.clip_start ?? 0;
  const ce = it.clip_end ?? (full > 0 ? full : MIN_REGION_WIDTH);
  return Math.max(round3(ce - cs), 0.05);
}

export function itemsToRegions(items: SeItem[], tracks: SeTrack[]): SeRegion[] {
  const durById = new Map(tracks.map((t) => [t.id, t.duration_sec ?? 0]));
  return items.map((it, idx) => {
    const w = clipWidth(it, durById.get(it.se_id) ?? 0);
    return { idx, start: it.time, end: round3(it.time + w), seId: it.se_id };
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

// SE 音源内の再生範囲を端ドラッグで変える (trim)。clip_start/clip_end を
// 0〜full duration にクランプし、最小 0.05s を保つ。
export function setItemClip(
  items: SeItem[],
  tracks: SeTrack[],
  idx: number,
  clipStart: number,
  clipEnd: number,
): SeItem[] {
  const full =
    tracks.find((t) => t.id === items[idx]?.se_id)?.duration_sec ?? 0;
  const max = full > 0 ? full : MIN_REGION_WIDTH;
  let cs = Math.max(0, Math.min(clipStart, max - 0.05));
  let ce = Math.min(max, Math.max(clipEnd, cs + 0.05));
  cs = round3(cs);
  ce = round3(ce);
  return items.map((it, i) =>
    i === idx ? { ...it, clip_start: cs, clip_end: ce } : it,
  );
}

// move 時に他 SE と区間が重ならない最寄り位置へ clamp する (1 レーン前提)。
export function clampNoOverlap(
  items: SeItem[],
  tracks: SeTrack[],
  idx: number,
  newTime: number,
): number {
  const regions = itemsToRegions(items, tracks);
  const myW = regions[idx].end - regions[idx].start;
  const others = regions
    .filter((_, i) => i !== idx)
    .map((r) => [r.start, r.end] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  let t = Math.max(0, newTime);
  for (let pass = 0; pass <= others.length; pass++) {
    let moved = false;
    for (const [s, e] of others) {
      if (t < e && t + myW > s) {
        const before = s - myW;
        const after = e;
        t =
          before >= 0 && Math.abs(newTime - before) <= Math.abs(newTime - after)
            ? before
            : after;
        moved = true;
      }
    }
    if (!moved) break;
  }
  return round3(Math.max(0, t));
}

export interface TimelineBlock {
  start: number;
  end: number;
  label: string;
}

interface SubtitleLike {
  text?: string;
  start?: number;
  end?: number;
}

export interface SceneLike {
  duration?: number;
  label?: string;
  lines?: {
    text?: string;
    start?: number;
    end?: number;
    subtitles?: SubtitleLike[];
  }[];
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

// subtitles[] チャンクを line 時間内に配分する。start/end が指定された chunk は
// それを優先し、auto (未指定) chunk は直前境界から文字数比例で埋める。
function distributeChunks(
  subs: SubtitleLike[],
  lineStart: number,
  lineEnd: number,
  base: number,
): TimelineBlock[] {
  const total = subs.reduce(
    (s, c) => s + Math.max((c.text ?? "").length, 1),
    0,
  );
  const span = Math.max(lineEnd - lineStart, 0.001);
  const out: TimelineBlock[] = [];
  let cur = lineStart;
  for (const c of subs) {
    const w = (Math.max((c.text ?? "").length, 1) / total) * span;
    const s = c.start != null ? c.start : cur;
    const e = c.end != null ? c.end : s + w;
    out.push({
      start: round3(base + s),
      end: round3(base + e),
      label: c.text ?? "",
    });
    cur = e;
  }
  return out;
}

// 各 line を絶対秒ブロックに (= 字幕トラック)。subtitles[] があれば画面表示と
// 同じチャンク単位、無ければ line 単位。scene 開始秒 = offsets (実尺) or 近似。
export function computeSubtitleBlocks(
  scenes: SceneLike[],
  offsets?: number[],
): TimelineBlock[] {
  const out: TimelineBlock[] = [];
  let acc = 0;
  scenes.forEach((sc, i) => {
    const base = offsets?.[i] ?? acc;
    for (const line of sc.lines ?? []) {
      const ls = line.start ?? 0;
      const le = line.end ?? line.start ?? 0;
      const subs = line.subtitles;
      if (subs && subs.length) {
        out.push(...distributeChunks(subs, ls, le, base));
      } else {
        out.push({
          start: round3(base + ls),
          end: round3(base + le),
          label: line.text ?? "",
        });
      }
    }
    acc += sc.duration ?? 0;
  });
  return out;
}
