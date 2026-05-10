import { useState } from "react";

import { api, ApiError } from "../api";

const ALLOWED_EXTS = [".mov", ".mp4", ".webm", ".mkv"] as const;

interface Props {
  /** 成功時のコールバック (= 通常 navigate(`/project/<TS>/analyze`)) */
  onSuccess: (ts: string, analyzeJobId: string) => void;
}

/**
 * TOP page の主動作 CTA。
 *
 * 参考動画 (multipart) と任意 instructions / fps を受け取り、
 * `POST /api/projects/from-reference-video` を呼ぶ。新規 project が
 * 1 トランザクションで作成され、Stage 0 (analyze) が即起動する。
 * 成功時の `onSuccess(ts, analyzeJobId)` を呼出側が拾って Stage 0 page
 * (= /project/<TS>/analyze) に遷移する想定。
 */
export default function CreateFromReferenceVideoSection({ onSuccess }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [instructions, setInstructions] = useState("");
  const [fps, setFps] = useState(2.0);
  const [busy, setBusy] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const [err, setErr] = useState<string | null>(null);

  const onSubmit = async () => {
    if (!file) {
      setErr("動画を選択してください");
      return;
    }
    setBusy(true);
    setErr(null);
    setUploadPct(0);
    try {
      const r = await api.createProjectFromReferenceVideo(
        file,
        { instructions: instructions || undefined, fps },
        (p) => setUploadPct(p),
      );
      onSuccess(r.ts, r.analyze_job_id);
    } catch (e) {
      if (e instanceof ApiError) {
        const body = e.body as Record<string, unknown> | undefined;
        const msg = (body?.message as string | undefined) ?? `HTTP ${e.status}`;
        setErr(msg);
      } else {
        setErr(String(e));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="card mb-8 border-2 border-emerald-600/40"
      data-testid="create-from-reference-video-section"
    >
      <h2 className="mb-3 text-lg font-semibold">📹 参考動画から作成</h2>
      <p className="mb-4 text-xs text-slate-400">
        参考動画をアップロードすると、Claude Vision で台本を自動生成し、
        新規プロジェクトを作成します。コスト確認モーダルが出るまで課金は
        発生しません。
      </p>

      <div className="space-y-3">
        <input
          type="file"
          accept={ALLOWED_EXTS.join(",")}
          disabled={busy}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm"
          aria-label="参考動画を選択"
        />
        {busy && uploadPct < 1 && (
          <div className="h-2 w-full overflow-hidden rounded bg-slate-700">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${Math.round(uploadPct * 100)}%` }}
            />
          </div>
        )}
        <textarea
          rows={2}
          placeholder="追加指示 (任意): 例: TikTok UI は無視"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          className="input w-full"
          disabled={busy}
        />
        <details className="text-xs text-slate-400">
          <summary className="cursor-pointer">高度な設定</summary>
          <label className="mt-2 flex items-center gap-2">
            フレーム抽出 fps:
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="5.0"
              value={fps}
              onChange={(e) => setFps(parseFloat(e.target.value) || 2.0)}
              className="input w-20"
              disabled={busy}
            />
          </label>
        </details>
        {err && (
          <div className="whitespace-pre-wrap text-sm text-rose-300">{err}</div>
        )}
        <button
          className="btn-primary w-full"
          disabled={!file || busy}
          onClick={onSubmit}
        >
          {busy ? "作成中..." : "📹 作成して分析を開始"}
        </button>
      </div>
    </section>
  );
}
