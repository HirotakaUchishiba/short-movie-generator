// IntentCatalogPage.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// part_registry の visual_intents.yaml を一覧表示。yaml ロード状態
// (loading / parse_error / missing) も visual に反映する。

import { useIntentCatalog } from "../../hooks/useIntentCatalog";

export function PartRegistrySection() {
  const state = useIntentCatalog();
  if (state.kind === "loading") {
    return (
      <section className="text-xs text-slate-500">
        intent catalog を取得中…
      </section>
    );
  }
  if (state.kind === "error") {
    return (
      <section className="text-xs text-rose-400">
        intent catalog エラー: {state.message}
      </section>
    );
  }
  const { entries, status } = state.data;
  return (
    <section className="space-y-3">
      <h2 className="text-base font-semibold">
        🎨 visual_intents (= clip_library hard match key)
      </h2>
      <div className="border border-slate-800 rounded p-3 bg-slate-900/40 text-xs space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[11px] text-emerald-300">
            visual_intents
          </span>
          <span className="text-[10px] text-slate-500">
            {entries.length} entries
          </span>
        </div>
        {status === "missing" && (
          <div className="text-[10px] text-rose-400">
            visual_intents.yaml が見つからない (= deploy 事故 / config 設定漏れ)
          </div>
        )}
        {status === "parse_error" && (
          <div className="text-[10px] text-rose-400">
            visual_intents.yaml 解析エラー (= ファイル破損)。サーバ log
            を確認してください
          </div>
        )}
        <ul className="space-y-0.5">
          {entries.map((entry) => (
            <li
              key={entry.id}
              className={
                "text-[10px] " +
                (entry.deprecated
                  ? "text-slate-600 line-through"
                  : "text-slate-300")
              }
              title={entry.description}
            >
              • {entry.id}
              {entry.deprecated && " (deprecated)"}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
