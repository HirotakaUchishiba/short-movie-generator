// QA failure 記録用 modal (Phase 0)。
// 各 stage ページから「✗ NG として記録」ボタン → このモーダル → /api/projects/<TS>/reject。
// 進捗 (generated_at / approved_at) には触らない。data/qa_failures/ への
// 不良サンプル蓄積だけが目的。
import { useMemo, useState } from "react";
import { api } from "../api";
import type { QaFailureTag, StageName } from "../types";
import {
  QA_AXIS_LABELS,
  QA_FAILURE_TAG_DEFS,
  type QaAxis,
  type QaFailureTagDef,
} from "../qaCategories";

interface Props {
  ts: string;
  stage: StageName;
  onClose: () => void;
  onSubmitted?: (failureId: number) => void;
}

export default function RejectModal({
  ts,
  stage,
  onClose,
  onSubmitted,
}: Props) {
  const [selected, setSelected] = useState<QaFailureTag[]>([]);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const grouped = useMemo(() => {
    const g: Record<QaAxis, QaFailureTagDef[]> = {
      visual: [],
      audio: [],
      lipsync: [],
      subtitle: [],
      story: [],
    };
    for (const d of QA_FAILURE_TAG_DEFS) g[d.axis].push(d);
    return g;
  }, []);

  const toggle = (tag: QaFailureTag) => {
    setSelected((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  };

  const submit = async () => {
    if (selected.length === 0) {
      setError("少なくとも 1 つのタグを選択してください");
      return;
    }
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

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-slate-800 p-6 rounded-lg w-[640px] max-h-[85vh] overflow-y-auto shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-xl font-bold mb-2">{stage} を NG として記録</h3>
        <p className="text-slate-400 text-sm mb-4">
          選択したタグと note は <code>data/qa_failures/</code> に保存されます。
          承認状態は変わらないので、必要なら別途「再生成」してください。
        </p>

        {(Object.keys(grouped) as QaAxis[]).map((axis) => (
          <div key={axis} className="mb-4">
            <h4 className="font-semibold text-slate-200 mb-2">
              {QA_AXIS_LABELS[axis]}
            </h4>
            <div className="grid grid-cols-2 gap-2">
              {grouped[axis].map((d) => (
                <label
                  key={d.tag}
                  className="flex items-center gap-2 cursor-pointer text-sm hover:bg-slate-700/40 px-2 py-1 rounded"
                >
                  <input
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
            メモ (任意)
          </label>
          <textarea
            className="w-full bg-slate-900 border border-slate-700 p-2 rounded text-sm"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="自由記述 (例: 2 シーン目のキャラの服装が変わった)"
          />
        </div>

        {error && <div className="text-rose-400 mb-3 text-sm">{error}</div>}

        <div className="flex gap-2 justify-end">
          <button
            className="btn-secondary"
            onClick={onClose}
            disabled={submitting}
          >
            キャンセル
          </button>
          <button
            className="btn-danger"
            onClick={submit}
            disabled={submitting || selected.length === 0}
          >
            {submitting ? "記録中..." : "✗ NG として記録"}
          </button>
        </div>
      </div>
    </div>
  );
}
