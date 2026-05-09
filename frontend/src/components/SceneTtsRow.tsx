import type { Line } from "../types";

// このシーンに割り当てられた TTS のセリフ本文を表示する共有コンポーネント。
// 背景 (bg) / Kling のシーンカードで使う。
// 実音声は 音声/リップシンク合成 以降で確認する想定なので audio タグは出さない。
export default function SceneTtsRow({ lines }: { lines: Line[] }) {
  return (
    <div className="rounded bg-slate-950/50 border border-slate-800 px-2 py-1.5">
      <div className="text-[10px] text-slate-500 mb-1">
        🔊 このシーンのセリフ ({lines.length} line)
      </div>
      <ol className="space-y-0.5 text-[11px] text-slate-200">
        {lines.map((line, i) => (
          <li key={line._uid ?? i} className="flex gap-2">
            <span className="text-slate-500 flex-shrink-0 w-8 text-right tabular-nums">
              {(line.start ?? 0).toFixed(1)}s
            </span>
            <span className="break-words">
              {line.text}
              {line.emotion && (
                <span className="ml-1 text-[10px] text-emerald-300">
                  [{line.emotion}]
                </span>
              )}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
