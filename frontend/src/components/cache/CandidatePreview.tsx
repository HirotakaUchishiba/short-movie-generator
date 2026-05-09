// 1 candidate を preview + 採用ボタン付きで表示する。
// 単一責務: 「候補 1 件の表示と『使用』ボタン」のみ。
// stage 別の preview / metadata 描画は presenter 経由で差し替える。
import type { CacheCandidate, CachePresenter, SceneContext } from "./types";

interface Props<TMeta> {
  candidate: CacheCandidate<TMeta>;
  sceneContext: SceneContext;
  isAdopted: boolean;
  busy: boolean;
  presenter: Pick<
    CachePresenter<TMeta>,
    "renderPreview" | "renderCandidateMeta"
  >;
  onUse: () => void;
}

export default function CandidatePreview<TMeta>({
  candidate,
  sceneContext,
  isAdopted,
  busy,
  presenter,
  onUse,
}: Props<TMeta>) {
  const fitnessPct = Math.round(candidate.fitness * 100);
  const hasWarning = candidate.warnings.length > 0;
  return (
    <div
      className={`flex flex-row gap-3 items-start p-2 rounded ${
        isAdopted
          ? "bg-emerald-900/20 border border-emerald-700/40"
          : "bg-slate-900/40"
      }`}
    >
      <div className="w-24 sm:w-28 aspect-[9/16] bg-slate-950 overflow-hidden rounded shrink-0">
        {presenter.renderPreview(candidate.key)}
      </div>
      <div className="flex-1 min-w-0 text-xs space-y-1">
        <div className="flex items-center gap-2">
          <span
            className={
              hasWarning
                ? "badge bg-amber-700 text-amber-100"
                : "badge bg-emerald-700 text-emerald-100"
            }
          >
            {hasWarning ? "♻️⚠️ 注意 hit" : "♻️ cache 候補"}
          </span>
          <span className="text-slate-400">
            適合度 <span className="font-mono">{fitnessPct}%</span>
          </span>
        </div>
        {presenter.renderCandidateMeta(candidate.meta, sceneContext)}
        {hasWarning && (
          <ul className="text-amber-300 space-y-0.5">
            {candidate.warnings.map((w, i) => (
              <li key={`${candidate.key}-${i}-${w}`}>⚠ {w}</li>
            ))}
          </ul>
        )}
        <div className="flex gap-2 pt-1">
          {isAdopted ? (
            <span className="badge bg-emerald-700 text-emerald-100">
              採用済み
            </span>
          ) : (
            <button
              className="btn-secondary text-xs"
              disabled={busy}
              onClick={onUse}
            >
              ♻️ このキャッシュを使用
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
