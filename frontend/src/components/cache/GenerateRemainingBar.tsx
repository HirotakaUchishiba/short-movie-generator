// 「残りの動画/画像を生成」ボタン (= sticky bottom)。
// 単一責務: 「全 scene 判断後に有効化される generate ボタン」のみ。
interface Props {
  totalCount: number;
  decidedCount: number;
  freshCount: number;
  totalFreshCost: number | null;
  generating: boolean;
  busy: boolean;
  assetLabel: string; // "動画" | "画像" など stage 別
  onGenerate: () => Promise<void>;
}

export default function GenerateRemainingBar({
  totalCount,
  decidedCount,
  freshCount,
  totalFreshCost,
  generating,
  busy,
  assetLabel,
  onGenerate,
}: Props) {
  const allDecided = decidedCount === totalCount;
  const costLabel =
    totalFreshCost == null ? "履歴不足" : `約 $${totalFreshCost.toFixed(2)}`;
  const description = allDecided
    ? `新規生成 ${freshCount} シーンを生成 (${costLabel})`
    : `判断済み ${decidedCount}/${totalCount} — 全シーン判断後に有効化`;
  return (
    <div className="card border-emerald-700/40 bg-emerald-900/10 sticky bottom-2">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">残りの{assetLabel}を生成</h3>
          <p className="text-xs text-slate-400 mt-1">{description}</p>
        </div>
        <button
          className="btn-primary"
          disabled={!allDecided || generating || busy}
          onClick={onGenerate}
        >
          {generating ? "実行中..." : `残りの${assetLabel}を生成`}
        </button>
      </div>
    </div>
  );
}
