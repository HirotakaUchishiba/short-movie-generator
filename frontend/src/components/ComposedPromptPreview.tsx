import { useEffect, useState } from "react";
import { api } from "../api";

// scene_gen の _build_background_prompt / _get_animation_prompt の合成結果を
// read-only でプレビュー表示する。微修正は Stage 1 / Stage 3-4 の構造化
// フィールド (location_ref / camera_distance / animation_style /
// character_selection) を介して行い、ここから直接プロンプト文を書き換える
// 経路は持たない (= SSOT 一本化、live derivation 維持)。
export default function ComposedPromptPreview({
  ts,
  sceneIdx,
  field,
  // refresh トリガー (TTS regen 後に dynamics が変わるので version で再fetch)
  version,
}: {
  ts: string;
  sceneIdx: number;
  field: "background_prompt" | "animation_prompt";
  version?: number | string;
}) {
  const [prompt, setPrompt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancel = false;
    setError(null);
    setPrompt(null);
    api
      .composedPrompts(ts, sceneIdx)
      .then((d) => {
        if (!cancel) setPrompt(d[field]);
      })
      .catch((e) => {
        if (!cancel) setError(String(e));
      });
    return () => {
      cancel = true;
    };
  }, [ts, sceneIdx, field, version]);

  return (
    <div className="mt-2 text-[10px]">
      <button
        type="button"
        className="text-slate-400 hover:text-slate-200"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "▼" : "▶"} このシーンのプロンプト ({fieldLabel(field)})
      </button>
      {open && (
        <div className="mt-1 p-2 rounded bg-slate-950/70 border border-slate-800 font-mono whitespace-pre-wrap break-words text-slate-300">
          {error ? `エラー: ${error}` : (prompt ?? "取得中...")}
        </div>
      )}
    </div>
  );
}

function fieldLabel(f: string): string {
  if (f === "background_prompt") return "Imagen 用";
  if (f === "animation_prompt") return "Kling 用";
  return f;
}
