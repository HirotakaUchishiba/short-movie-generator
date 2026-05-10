// Path-only shallow copy helpers for screenplay state.
//
// 旧 StageOverlay は setDraft で `JSON.parse(JSON.stringify(d))` で screenplay
// 全体を deep clone していたため、1 line の text を変えるだけで全 scene / 全
// line / 全 chunk が直列化される問題があった。ここにある helpers は path 上の
// 配列 / オブジェクトだけを新規作成し、関係ない兄弟参照は共有する。
//
// 不変条件:
//   - 入力 screenplay 自体は mutate しない (= immutable update)
//   - 触らない兄弟 scene / line / chunk は同じ参照を保持する (= memo / React の
//     === 比較で短絡可能)
//   - mut 関数は新オブジェクトを **return** すること (= mut が引数を直接書き換えても
//     バグになる)
import type { Line, Screenplay, SubtitleChunk } from "../types";

export function replaceScene(
  d: Screenplay,
  sIdx: number,
  mut: (s: Screenplay["scenes"][number]) => Screenplay["scenes"][number],
): Screenplay {
  const scenes = d.scenes.slice();
  scenes[sIdx] = mut(scenes[sIdx]);
  return { ...d, scenes };
}

export function replaceLine(
  d: Screenplay,
  sIdx: number,
  lIdx: number,
  mut: (l: Line) => Line,
): Screenplay {
  return replaceScene(d, sIdx, (scene) => {
    const lines = (scene.lines ?? []).slice();
    lines[lIdx] = mut(lines[lIdx]);
    return { ...scene, lines };
  });
}

export function replaceChunk(
  d: Screenplay,
  sIdx: number,
  lIdx: number,
  cIdx: number,
  mut: (c: SubtitleChunk) => SubtitleChunk,
): Screenplay {
  return replaceLine(d, sIdx, lIdx, (line) => {
    const subs = (line.subtitles ?? []).slice();
    subs[cIdx] = mut(subs[cIdx]);
    return { ...line, subtitles: subs };
  });
}
