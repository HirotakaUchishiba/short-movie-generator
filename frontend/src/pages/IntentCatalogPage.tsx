import { Link } from "react-router-dom";

import { ClipLibrarySection } from "./intent-catalog/ClipLibrarySection";
import { IntentSuggestionsSection } from "./intent-catalog/IntentSuggestionsSection";
import { PartRegistrySection } from "./intent-catalog/PartRegistrySection";

/**
 * IntentCatalog 画面 = Compositional Architecture の運用ダッシュボード。
 * 構成:
 *   1. novel intent suggestions の一覧 + 採用 / 却下 / yaml snippet 取得
 *   2. clip_library entry の一覧 + 承認 / blacklist 操作
 *   3. part_registry catalog の閲覧 (= 各 category の利用可能 id を確認)
 *
 * 設計 ref:
 *   - docs/plannings/2026-05-10_compositional-architecture.md §3-4
 *   - docs/plannings/2026-05-10_intent-suggestion-flow.md §4
 */
export default function IntentCatalogPage() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <header className="px-6 py-4 border-b border-slate-800 flex items-center gap-4">
        <Link to="/" className="text-sm text-slate-400 hover:text-emerald-300">
          ← プロジェクト一覧
        </Link>
        <h1 className="text-lg font-semibold">
          🗂 Intent Catalog (= 提案 + clip_library + part_registry 運用)
        </h1>
      </header>
      <div className="max-w-6xl mx-auto p-6 space-y-8">
        <IntentSuggestionsSection />
        <ClipLibrarySection />
        <PartRegistrySection />
      </div>
    </div>
  );
}
