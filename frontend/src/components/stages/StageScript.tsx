import { useState } from "react";
import { useShellCtx } from "../StageGate";
import StageGate from "../StageGate";
import type { Screenplay } from "../../types";
import ScriptEditPanel from "./ScriptEditPanel";

export default function StageScript() {
  const ctx = useShellCtx();
  const [showJson, setShowJson] = useState(false);

  const sp = ctx.detail.screenplay;
  const totalLines = sp.scenes.reduce((a, s) => a + (s.lines?.length ?? 0), 0);
  const totalDuration = sp.scenes.reduce((a, s) => a + s.duration, 0);

  return (
    <StageGate
      stage="script"
      title="台本"
      description="台本 (caption + シーン + セリフ) を確認・編集します。analyze 経由のプロジェクトでは「素材編集」セクションで抽象台本を編集して再合成できます。OK を押すまで次のステージには進みません。"
    >
      <div className="mb-4 flex items-center gap-3 flex-wrap">
        <button
          className="btn-secondary text-xs"
          onClick={() => setShowJson(true)}
          title="現在の screenplay JSON を全文表示します (read-only)"
        >
          🛠 現在の JSON を表示
        </button>
        <span className="text-xs text-slate-500">
          {sp.scenes.length} シーン · {totalLines} セリフ ·{" "}
          {totalDuration.toFixed(1)}s
        </span>
      </div>

      {ctx.detail.analyze_job_id ? (
        <ScriptEditPanel
          ts={ctx.detail.timestamp}
          jobId={ctx.detail.analyze_job_id}
        />
      ) : (
        <div className="card text-sm text-slate-300">
          手書き台本プロジェクト (analyze 経由ではありません)。 screenplay
          の内容は上の「現在の JSON を表示」で確認し、問題なければ右上の OK
          ボタンで承認してください。
        </div>
      )}

      {showJson && (
        <JsonModal screenplay={sp} onClose={() => setShowJson(false)} />
      )}
    </StageGate>
  );
}

function JsonModal({
  screenplay,
  onClose,
}: {
  screenplay: Screenplay;
  onClose: () => void;
}) {
  const text = JSON.stringify(screenplay, null, 2);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-4xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-slate-700 px-4 py-2">
          <h3 className="text-sm font-semibold">現在の screenplay JSON</h3>
          <button className="btn-ghost text-xs" onClick={onClose}>
            × 閉じる
          </button>
        </header>
        <pre className="flex-1 overflow-auto text-xs font-mono p-3 bg-slate-950 whitespace-pre-wrap">
          {text}
        </pre>
      </div>
    </div>
  );
}
