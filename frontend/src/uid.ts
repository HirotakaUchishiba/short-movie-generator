// React の key prop に使う安定 ID を screenplay / abstract に注入する。
//
// scenes / lines / subtitles の配列は UI 側で追加・削除・並び替えが起きるため、
// index を key にすると「削除すると別要素の state が引き継がれる」React 公式の
// アンチパターンになる。サーバ側 schema は手書き screenplay も入力に取るため
// id を要求できず、また安定 ID を運ぶフィールドも仕様上存在しない。
//
// 解決として API レスポンス受信時に各 array element へ `_uid` を注入し、
// API 送信時に剥がす。`_uid` は JSON フィールドなので `JSON.parse(JSON.stringify())`
// による deep clone で保存される。新しい要素を作る箇所 (split / append / 新規追加)
// では `freshUid()` で uid を発行する。
import type {
  AbstractLine,
  AbstractScene,
  AbstractScreenplay,
  Line,
  Scene,
  Screenplay,
  SubtitleChunk,
} from "./types";

let _counter = 0;

export function freshUid(): string {
  // crypto.randomUUID は jsdom (vitest) でも提供されるが、念のため fallback。
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  _counter += 1;
  return `uid-${Date.now().toString(36)}-${_counter}`;
}

function ensureUid<T extends { _uid?: string }>(obj: T): T {
  if (!obj._uid) obj._uid = freshUid();
  return obj;
}

export function attachUidsToScreenplay(sp: Screenplay): Screenplay {
  for (const scene of sp.scenes ?? []) {
    attachUidsToScene(scene);
  }
  return sp;
}

function attachUidsToScene(scene: Scene): Scene {
  ensureUid(scene);
  for (const line of scene.lines ?? []) {
    ensureUid(line);
    for (const chunk of line.subtitles ?? []) {
      ensureUid(chunk);
    }
  }
  return scene;
}

export function attachUidsToAbstract(
  ab: AbstractScreenplay,
): AbstractScreenplay {
  for (const scene of ab.scenes ?? []) {
    attachUidsToAbstractScene(scene);
  }
  return ab;
}

function attachUidsToAbstractScene(scene: AbstractScene): AbstractScene {
  ensureUid(scene);
  for (const line of scene.lines ?? []) {
    ensureUid(line);
  }
  return scene;
}

export function stripUids<T>(value: T): T {
  return JSON.parse(
    JSON.stringify(value, (key, v) => (key === "_uid" ? undefined : v)),
  ) as T;
}

// テスト/開発用ヘルパ。SubtitleChunk / Line / Scene / AbstractLine / AbstractScene
// に対して uid を新規発行して付与する。
export function withFreshUid<
  T extends Scene | Line | SubtitleChunk | AbstractScene | AbstractLine,
>(obj: T): T {
  obj._uid = freshUid();
  return obj;
}
