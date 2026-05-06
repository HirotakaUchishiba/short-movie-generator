// 1 scene 分の判断カード。candidates / decision バッジ / 操作ボタン / scene 別 extras を集約する。
// 単一責務: 「1 scene の判断 UI を組み立てる」のみ。
// state 管理は親 (CacheDecisionFlow) が持ち、操作は callback で受ける。
import { useState } from "react";
import CandidatePreview from "./CandidatePreview";
import type { CachePresenter, SceneDecision } from "./types";

interface Props<TMeta> {
  sceneIdx: number;
  decision: SceneDecision<TMeta> | undefined;
  presenter: CachePresenter<TMeta>;
  onUseCache: (key: string) => Promise<void>;
  onQueueFresh: () => Promise<void>;
  onRescan: () => Promise<void>;
}

export default function SceneDecisionCard<TMeta>({
  sceneIdx,
  decision,
  presenter,
  onUseCache,
  onQueueFresh,
  onRescan,
}: Props<TMeta>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wrap = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!decision || decision.diagnostics.length > 0) {
    return (
      <div className="card border-slate-700/60 bg-slate-900/40">
        <div className="text-sm font-semibold mb-2">シーン {sceneIdx + 1}</div>
        <div className="text-xs text-slate-400">
          スキャン不可:{" "}
          {decision?.diagnostics?.join(" / ") ?? "decision is missing"}
        </div>
      </div>
    );
  }

  const candidates = decision.candidates ?? [];
  const hasCandidate = candidates.length > 0;
  const decided =
    decision.decision === "cache" || decision.decision === "fresh";
  const sceneCtx = presenter.contextForScene(sceneIdx);
  const cost = presenter.costForScene(sceneIdx);

  const decisionBadge = (() => {
    if (decision.decision === "cache") {
      return (
        <span className="badge bg-emerald-700 text-emerald-100">
          ♻️ cache 採用済み
        </span>
      );
    }
    if (decision.decision === "fresh") {
      return (
        <span className="badge bg-amber-700 text-amber-100">
          {hasCandidate ? "✨ 新規生成 (cache 拒否)" : "✨ 新規生成 (候補なし)"}
        </span>
      );
    }
    return (
      <span className="badge bg-slate-700 text-slate-300">⏸️ 判断待ち</span>
    );
  })();

  return (
    <div
      className={`card ${
        decided ? "border-slate-700/40" : "border-amber-700/40 bg-amber-900/5"
      }`}
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="text-sm font-semibold">シーン {sceneIdx + 1}</div>
        {decisionBadge}
      </div>

      {hasCandidate && (
        <div className="space-y-3 mb-3">
          {candidates.map((c) => (
            <CandidatePreview
              key={c.key}
              candidate={c}
              sceneContext={sceneCtx}
              isAdopted={decision.decided_key === c.key}
              busy={busy}
              presenter={presenter}
              onUse={() => wrap(() => onUseCache(c.key))}
            />
          ))}
        </div>
      )}

      {!hasCandidate && (
        <div className="text-xs text-slate-400 mb-3">
          cache 候補なし。新規生成します。
        </div>
      )}

      {presenter.renderSceneExtras?.(sceneIdx)}

      {error && <div className="text-rose-400 text-xs mb-2">{error}</div>}

      <div className="flex flex-wrap gap-2 justify-end items-center">
        <button
          className="btn-ghost text-xs"
          disabled={busy}
          onClick={() => wrap(onRescan)}
        >
          🔄 このシーンを再スキャン
        </button>
        {decision.decision !== "fresh" && (
          <button
            className="btn-secondary text-xs"
            disabled={busy}
            onClick={() => wrap(onQueueFresh)}
          >
            ✨ 新規生成 ({cost == null ? "履歴不足" : `$${cost.toFixed(2)}`})
          </button>
        )}
      </div>
    </div>
  );
}
