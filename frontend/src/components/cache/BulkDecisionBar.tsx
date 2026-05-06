// 全 scene の一括判断ボタンと進捗カウンタ。
// 単一責務: 「scan / 一括判断 / 進捗表示」のみ。実際の実行は callback。
import { useState } from "react";

interface Props {
  decidedCount: number;
  totalCount: number;
  candidatesCount: number;
  totalFreshCost: number | null;
  scanning: boolean;
  busy: boolean;
  onRescan: () => Promise<void>;
  onBulk: (action: "all-cache" | "all-fresh") => Promise<void>;
}

export default function BulkDecisionBar({
  decidedCount,
  totalCount,
  candidatesCount,
  totalFreshCost,
  scanning,
  busy,
  onRescan,
  onBulk,
}: Props) {
  const [pending, setPending] = useState<null | "all-cache" | "all-fresh">(
    null,
  );

  const exec = async (action: "all-cache" | "all-fresh") => {
    setPending(null);
    await onBulk(action);
  };

  return (
    <div className="card border-amber-700/40 bg-amber-900/10">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">
            判断状況 {decidedCount}/{totalCount}
            {candidatesCount > 0 && (
              <span className="text-xs text-slate-400 ml-2">
                ({candidatesCount} シーンに cache 候補あり)
              </span>
            )}
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            新規生成予定の合計コスト:{" "}
            <span className="text-rose-300 font-mono">
              {totalFreshCost == null
                ? "履歴不足"
                : `$${totalFreshCost.toFixed(2)}`}
            </span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="btn-ghost text-xs"
            onClick={onRescan}
            disabled={scanning || busy}
          >
            {scanning ? "再スキャン中..." : "🔄 再スキャン"}
          </button>
          <button
            className="btn-secondary text-xs"
            onClick={() => setPending("all-cache")}
            disabled={busy}
          >
            ♻️ 全 cache 採用
          </button>
          <button
            className="btn-secondary text-xs"
            onClick={() => setPending("all-fresh")}
            disabled={busy}
          >
            ✨ 全 新規生成
          </button>
        </div>
      </div>
      {pending && (
        <div className="mt-3 p-3 bg-slate-900/60 rounded text-xs">
          {pending === "all-cache" ? (
            <p className="mb-2">
              cache 候補のある全シーンを採用します。注意 hit (♻️⚠️)
              も含めて自動採用されます。候補なしのシーンは新規生成です。
            </p>
          ) : (
            <p className="mb-2">
              全シーンを新規生成キューに変更します。既に cache 採用済みの
              成果物は破棄されます。
            </p>
          )}
          <div className="flex gap-2">
            <button
              className="btn-ghost text-xs"
              onClick={() => setPending(null)}
            >
              キャンセル
            </button>
            <button
              className="btn-primary text-xs"
              onClick={() => exec(pending)}
            >
              実行
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
