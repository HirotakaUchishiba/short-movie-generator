import { useState } from "react";
import { api } from "../api";

type Field = "background_prompt" | "animation_prompt";

type PreviewState = {
  previous: string;
  revised: string;
  model: string;
};

const FIELD_LABEL: Record<Field, string> = {
  background_prompt: "背景プロンプト",
  animation_prompt: "アニメーションプロンプト",
};

const PLACEHOLDER: Record<Field, string> = {
  background_prompt:
    "例: もっとカメラを引いて、左奥に窓辺を加えて。机の上のマグカップは赤に。",
  animation_prompt:
    "例: 最初に深呼吸してから笑顔になる流れに。カメラを少しだけ寄せて。",
};

export default function PromptRevisePanel({
  ts,
  sceneIdx,
  field,
  onApplied,
}: {
  ts: string;
  sceneIdx: number;
  field: Field;
  onApplied?: (revised: string) => void | Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [editedRevised, setEditedRevised] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setPreview(null);
    setEditedRevised("");
    setError(null);
  };

  const onPreview = async () => {
    if (!instruction.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.previewRevisePrompt(ts, sceneIdx, field, instruction);
      setPreview({
        previous: r.previous,
        revised: r.revised,
        model: r.model,
      });
      setEditedRevised(r.revised);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const onApply = async () => {
    if (!preview || !editedRevised.trim()) return;
    setApplying(true);
    setError(null);
    try {
      await api.applyRevisePrompt(
        ts,
        sceneIdx,
        field,
        editedRevised,
        instruction,
      );
      await onApplied?.(editedRevised);
      setInstruction("");
      reset();
    } catch (e) {
      setError(String(e));
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="rounded border border-sky-700/40 bg-sky-900/10 px-2 py-2 mb-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold text-sky-200">
          日本語で修正案を入力 ({FIELD_LABEL[field]})
        </div>
        <button
          className="btn-ghost text-xs"
          onClick={() => {
            setOpen((v) => !v);
            if (open) reset();
          }}
        >
          {open ? "閉じる" : "開く"}
        </button>
      </div>

      {open && (
        <div className="mt-2 space-y-2">
          <textarea
            className="input text-xs h-16"
            placeholder={PLACEHOLDER[field]}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            disabled={loading || applying}
          />
          <div className="flex justify-end gap-2">
            {preview && (
              <button
                className="btn-ghost text-xs"
                onClick={reset}
                disabled={loading || applying}
              >
                破棄
              </button>
            )}
            <button
              className="btn-secondary text-xs"
              onClick={onPreview}
              disabled={!instruction.trim() || loading || applying}
              title="日本語修正指示を Claude に渡し、英語プロンプトを書き換える"
            >
              {loading ? "生成中..." : preview ? "再生成" : "修正案を生成"}
            </button>
          </div>

          {error && <div className="text-rose-400">{error}</div>}

          {preview && (
            <div className="space-y-2 border-t border-slate-700/40 pt-2">
              <div>
                <div className="text-slate-500 mb-0.5">変更前</div>
                <p className="font-mono text-[11px] break-words text-slate-400 whitespace-pre-wrap">
                  {preview.previous}
                </p>
              </div>
              <div>
                <div className="text-slate-500 mb-0.5">
                  変更後 (編集可・モデル: {preview.model})
                </div>
                <textarea
                  className="input text-xs h-24 font-mono"
                  value={editedRevised}
                  onChange={(e) => setEditedRevised(e.target.value)}
                  disabled={applying}
                />
              </div>
              <div className="flex justify-end">
                <button
                  className="btn-primary text-xs"
                  onClick={onApply}
                  disabled={!editedRevised.trim() || applying}
                  title="この prompt を screenplay に保存する"
                >
                  {applying ? "適用中..." : "プロンプトに反映"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
