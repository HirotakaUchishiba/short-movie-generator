// StageOverlay.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 字幕チャンクを手動編集する UI。各 chunk の text / start / end を編集し、
// start/end は空欄 (= auto: 文字数比例配分) か手打ち時刻のどちらかを取る。
// 分割 / 削除 / 末尾追加 / auto に戻すボタンも提供する。

import type { SubtitleChunk } from "../../types";
import { TimeField } from "./TimeField";

export function ManualChunksEditor({
  sIdx,
  chunks,
  onChangeText,
  onChangeTime,
  onSnap,
  onClearTime,
  onSplit,
  onRemove,
  onAppend,
}: {
  sIdx: number;
  chunks: SubtitleChunk[];
  onChangeText: (cIdx: number, text: string) => void;
  onChangeTime: (
    cIdx: number,
    field: "start" | "end",
    value: number | undefined,
  ) => void;
  onSnap: (cIdx: number, field: "start" | "end") => void;
  onClearTime: (cIdx: number) => void;
  onSplit: (cIdx: number) => void;
  onRemove: (cIdx: number) => void;
  onAppend: () => void;
}) {
  return (
    <div className="mt-2 ml-12 border-l-2 border-amber-700/40 pl-3">
      <div className="text-[10px] text-slate-500 mb-1">
        S{sIdx + 1} — 空欄の時刻は line 範囲を文字数比例で自動配分
      </div>
      {chunks.map((c, cIdx) => {
        const isAuto = c.start === undefined && c.end === undefined;
        return (
          <div
            key={c._uid ?? cIdx}
            className="border-t border-slate-800 py-1.5 flex flex-col gap-1"
          >
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-500 w-4">{cIdx + 1}</span>
              <input
                type="text"
                className="input text-xs py-1 flex-1"
                value={c.text}
                placeholder="字幕テキスト"
                onChange={(e) => onChangeText(cIdx, e.target.value)}
              />
              <span
                className={
                  "text-[10px] px-1 rounded " +
                  (isAuto
                    ? "bg-slate-700 text-slate-400"
                    : "bg-amber-700/40 text-amber-200")
                }
              >
                {isAuto ? "auto" : "手打ち"}
              </span>
              <button
                className="btn-ghost text-[10px]"
                onClick={() => onSplit(cIdx)}
                title="このチャンクを文字数中央で 2 分割"
              >
                分割
              </button>
              <button
                className="btn-ghost text-[10px] text-rose-400"
                onClick={() => onRemove(cIdx)}
              >
                ×
              </button>
            </div>
            <div className="flex items-center gap-1.5 pl-6">
              <TimeField
                label="start"
                value={c.start}
                onChange={(v) => onChangeTime(cIdx, "start", v)}
                onSnap={() => onSnap(cIdx, "start")}
              />
              <TimeField
                label="end"
                value={c.end}
                onChange={(v) => onChangeTime(cIdx, "end", v)}
                onSnap={() => onSnap(cIdx, "end")}
              />
              {!isAuto && (
                <button
                  className="btn-ghost text-[10px]"
                  onClick={() => onClearTime(cIdx)}
                  title="時刻をクリアして auto (文字数比例配分) に戻す"
                >
                  auto に戻す
                </button>
              )}
            </div>
          </div>
        );
      })}
      <button
        className="btn-ghost text-[10px] mt-2"
        onClick={onAppend}
        title="末尾にチャンクを追加 (時刻は auto)"
      >
        + チャンク追加
      </button>
    </div>
  );
}
