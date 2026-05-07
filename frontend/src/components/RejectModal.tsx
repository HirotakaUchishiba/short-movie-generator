// QA failure 記録用 modal (Phase 0)。
// 各 stage ページから「✗ NG として記録」ボタン → このモーダル → /api/projects/<TS>/reject。
// 進捗 (generated_at / approved_at) には触らない。data/qa_failures/ への
// 不良サンプル蓄積だけが目的。
//
// タグ一覧は backend SSOT (/api/config/qa-tags) から取得する。
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { StageName } from "../types";
import { useQaTags, type QaFailureTagDef } from "../qaCategories";

interface Props {
  ts: string;
  stage: StageName;
  onClose: () => void;
  onSubmitted?: (failureId: number) => void;
}

const NOTE_MAX_LENGTH = 2000;

export default function RejectModal({
  ts,
  stage,
  onClose,
  onSubmitted,
}: Props) {
  const qaTags = useQaTags();
  const [selected, setSelected] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const firstCheckboxRef = useRef<HTMLInputElement | null>(null);
  const cancelButtonRef = useRef<HTMLButtonElement | null>(null);

  // ESC で閉じる + 開いた瞬間にフォーカスを最初の checkbox (= 無ければキャンセル)
  // へ移してキー操作だけで完結できるようにする。focus trap は Phase 1 で。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, submitting]);

  useEffect(() => {
    if (qaTags && firstCheckboxRef.current) {
      firstCheckboxRef.current.focus();
    } else if (!qaTags && cancelButtonRef.current) {
      cancelButtonRef.current.focus();
    }
  }, [qaTags]);

  const grouped = useMemo(() => {
    if (!qaTags) return null;
    const g = new Map<string, QaFailureTagDef[]>();
    for (const d of qaTags.tags) {
      const list = g.get(d.axis);
      if (list) list.push(d);
      else g.set(d.axis, [d]);
    }
    return g;
  }, [qaTags]);

  const toggle = (tag: string) => {
    setSelected((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.reject(ts, {
        stage,
        tags: selected,
        note: note.trim() || undefined,
      });
      onSubmitted?.(res.failure_id);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const noteOver = note.length > NOTE_MAX_LENGTH;

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="reject-modal-title"
    >
      <div
        className="bg-slate-800 p-6 rounded-lg w-[640px] max-h-[85vh] overflow-y-auto shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="reject-modal-title" className="text-xl font-bold mb-2">
          {stage} を NG として記録
        </h3>
        <p className="text-slate-400 text-sm mb-4">
          選択したタグと note は <code>data/qa_failures/</code> に保存されます。
          承認状態は変わらないので、必要なら別途「再生成」してください。
        </p>

        {!qaTags && (
          <div className="text-slate-400 mb-4 text-sm">
            タグ一覧を読み込み中…
          </div>
        )}

        {qaTags &&
          grouped &&
          Array.from(grouped.entries()).map(([axis, defs], axisIdx) => (
            <div key={axis} className="mb-4">
              <h4 className="font-semibold text-slate-200 mb-2">
                {qaTags.axis_labels[axis] ?? axis}
              </h4>
              <div className="grid grid-cols-2 gap-2">
                {defs.map((d, i) => (
                  <label
                    key={d.tag}
                    className="flex items-center gap-2 cursor-pointer text-sm hover:bg-slate-700/40 px-2 py-1 rounded"
                  >
                    <input
                      ref={axisIdx === 0 && i === 0 ? firstCheckboxRef : null}
                      type="checkbox"
                      checked={selected.includes(d.tag)}
                      onChange={() => toggle(d.tag)}
                    />
                    <span>{d.label}</span>
                  </label>
                ))}
              </div>
            </div>
          ))}

        <div className="mb-4">
          <label className="block text-sm mb-1 text-slate-300">
            メモ (任意 / 最大 {NOTE_MAX_LENGTH} 文字)
          </label>
          <textarea
            className="w-full bg-slate-900 border border-slate-700 p-2 rounded text-sm"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="自由記述 (例: 2 シーン目のキャラの服装が変わった)"
          />
          {noteOver && (
            <div className="text-rose-400 text-xs mt-1">
              {note.length} / {NOTE_MAX_LENGTH} — 上限を超えています
            </div>
          )}
        </div>

        {error && <div className="text-rose-400 mb-3 text-sm">{error}</div>}

        <div className="flex gap-2 justify-end">
          <button
            ref={cancelButtonRef}
            className="btn-secondary"
            onClick={onClose}
            disabled={submitting}
          >
            キャンセル
          </button>
          <button
            className="btn-danger"
            onClick={submit}
            disabled={submitting || selected.length === 0 || noteOver}
          >
            {submitting ? "記録中..." : "✗ NG として記録"}
          </button>
        </div>
      </div>
    </div>
  );
}
