import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useIntentCatalog } from "../hooks/useIntentCatalog";

// `/api/clips` の Response 型 (= routes/clip_library.py の出力)。
// 既存 types.ts には載せていないため、本 page でローカル定義。
type ClipEntry = {
  id: string;
  identity: {
    character_refs: string[];
    location_ref: string;
    start_emotion: string;
    camera_distance?: string;
  };
  annotation: {
    visual_intent_id?: string | null;
    duration_bucket?: number | null;
    motion_intensity?: string;
    generation_seed?: number | null;
  };
  provenance: {
    source_screenplay?: string | null;
    source_scene_idx?: number | null;
    generated_at?: string;
  };
  lifecycle: {
    status: "pending_review" | "active" | "blacklisted" | string;
    approved_at?: string | null;
    hit_count: number;
    last_used_at?: string | null;
    blacklisted: boolean;
    blacklist_reason?: string | null;
  };
};

type ClipsResponse = { enabled: boolean; entries: ClipEntry[] };

type StatusFilter = "all" | "active" | "pending_review" | "blacklisted";

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

// ───────────── novel intent suggestions ─────────────

type SuggestionStatus =
  | "new"
  | "reviewing"
  | "accepted"
  | "dismissed"
  | "merged";

type SuggestionEntry = {
  id: string;
  proposed_id: string;
  description: string;
  rationale: string;
  scene_indices: number[];
  source_screenplay: string;
  source_analyze_job_id: string | null;
  status: SuggestionStatus;
  dismissed_reason: string | null;
  occurrences: number;
  created_at: string;
  updated_at: string;
};

type SuggestionsResponse = {
  entries: SuggestionEntry[];
  counts: Record<SuggestionStatus, number>;
};

type SuggestionFilter = "all" | SuggestionStatus;

const SUGGESTION_FILTERS: SuggestionFilter[] = [
  "all",
  "new",
  "reviewing",
  "accepted",
  "dismissed",
  "merged",
];

function suggestionStatusColor(status: SuggestionStatus): string {
  switch (status) {
    case "new":
      return "bg-sky-700/40 text-sky-200";
    case "reviewing":
      return "bg-amber-700/40 text-amber-200";
    case "accepted":
      return "bg-emerald-700/40 text-emerald-200";
    case "dismissed":
      return "bg-slate-700/40 text-slate-300";
    case "merged":
      return "bg-violet-700/40 text-violet-200";
  }
}

function IntentSuggestionsSection() {
  const [data, setData] = useState<SuggestionsResponse | null>(null);
  const [filter, setFilter] = useState<SuggestionFilter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [snippets, setSnippets] = useState<Record<string, string>>({});
  const [toast, setToast] = useState<string | null>(null);
  const sectionRef = useRef<HTMLElement | null>(null);
  const location = useLocation();

  const reload = () => {
    setError(null);
    fetch(`/api/intent-suggestions?status=${filter}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
        return r.json();
      })
      .then((d: SuggestionsResponse) => setData(d))
      .catch((e) => setError(String(e)));
  };
  useEffect(reload, [filter]);

  // /intent-catalog#suggestions でジャンプされたら scroll
  useEffect(() => {
    if (location.hash === "#suggestions" && sectionRef.current) {
      sectionRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [location.hash, data]);

  const showToast = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 3500);
  };

  const onMarkReviewing = async (id: string) => {
    setBusy(id);
    try {
      const r = await fetch(`/api/intent-suggestions/${id}/mark-reviewing`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
      reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const onDismiss = async (id: string) => {
    const reason = window.prompt("却下理由 (= 後で見直すため必須):", "");
    if (!reason || !reason.trim()) return;
    setBusy(id);
    try {
      const r = await fetch(`/api/intent-suggestions/${id}/dismiss`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
      reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const onAccept = async (id: string) => {
    setBusy(id);
    try {
      const r = await fetch(`/api/intent-suggestions/${id}/accept`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
      const body = (await r.json()) as {
        yaml_snippet: string;
        record: SuggestionEntry;
      };
      setSnippets((prev) => ({ ...prev, [id]: body.yaml_snippet }));
      try {
        await navigator.clipboard.writeText(body.yaml_snippet);
        showToast(
          "snippet をコピーしました。config/part_registry/visual_intents.yaml に貼り付け、PR を作成してください",
        );
      } catch {
        showToast(
          "snippet を生成しました (= clipboard が使えない環境のため、下のプレビューから手動コピーしてください)",
        );
      }
      reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const copySnippet = async (id: string) => {
    const text = snippets[id];
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showToast("snippet を再コピーしました");
    } catch {
      // 失敗時は select-all で手動コピーさせる以外打ち手がない
      showToast("clipboard が使えません。下のプレビューを手動選択してください");
    }
  };

  return (
    <section
      ref={sectionRef}
      id="suggestions"
      className="space-y-3 scroll-mt-4"
      data-testid="intent-suggestions-section"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">💡 提案中の novel intent</h2>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">フィルタ:</span>
          {SUGGESTION_FILTERS.map((s) => (
            <button
              key={s}
              className={
                "px-2 py-0.5 rounded border text-[11px] " +
                (filter === s
                  ? "bg-emerald-700/40 border-emerald-500 text-emerald-100"
                  : "bg-slate-800/40 border-slate-700 text-slate-400 hover:text-slate-200")
              }
              onClick={() => setFilter(s)}
            >
              {s}
              {data && s !== "all" && (
                <span className="ml-1 text-[9px] text-slate-400">
                  ({data.counts[s] ?? 0})
                </span>
              )}
            </button>
          ))}
        </div>
      </div>
      {error && <div className="text-xs text-rose-400">エラー: {error}</div>}
      {toast && (
        <div
          className="text-xs text-emerald-300 bg-emerald-900/30 border border-emerald-800 rounded px-3 py-2"
          role="status"
        >
          {toast}
        </div>
      )}
      {data && data.entries.length === 0 && (
        <div className="text-xs text-slate-500 italic">
          (該当 entry なし。analyze 実行で confidence 低が連続するシーンが
          見つかると候補がここに登録されます)
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {(data?.entries ?? []).map((e) => (
          <SuggestionCard
            key={e.id}
            entry={e}
            busy={busy === e.id}
            snippet={snippets[e.id]}
            onMarkReviewing={() => onMarkReviewing(e.id)}
            onDismiss={() => onDismiss(e.id)}
            onAccept={() => onAccept(e.id)}
            onCopySnippet={() => copySnippet(e.id)}
          />
        ))}
      </div>
    </section>
  );
}

function SuggestionCard({
  entry,
  busy,
  snippet,
  onMarkReviewing,
  onDismiss,
  onAccept,
  onCopySnippet,
}: {
  entry: SuggestionEntry;
  busy: boolean;
  snippet: string | undefined;
  onMarkReviewing: () => void;
  onDismiss: () => void;
  onAccept: () => void;
  onCopySnippet: () => void;
}) {
  const isTerminal = entry.status === "dismissed" || entry.status === "merged";
  return (
    <div
      className="border border-slate-800 rounded p-3 bg-slate-900/40 text-xs space-y-2"
      data-testid="suggestion-card"
    >
      <div className="flex items-center gap-2">
        <span className="font-mono text-[11px] text-emerald-300 truncate">
          {entry.proposed_id}
        </span>
        <span
          className={
            "text-[10px] px-1.5 py-0.5 rounded " +
            suggestionStatusColor(entry.status)
          }
        >
          {entry.status}
        </span>
        {entry.occurrences > 1 && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-200"
            title="同じ候補が複数回検出されたため、採用優先度が高い可能性があります"
          >
            ×{entry.occurrences}
          </span>
        )}
      </div>
      <div className="text-[11px] text-slate-300">
        <span className="text-slate-500">description:</span> {entry.description}
      </div>
      <div className="text-[11px] text-slate-400">
        <span className="text-slate-500">rationale:</span> {entry.rationale}
      </div>
      <div className="text-[10px] text-slate-500 truncate">
        scenes: [{entry.scene_indices.join(", ")}] · source:{" "}
        {entry.source_screenplay}
      </div>
      {entry.dismissed_reason && (
        <div className="text-[10px] text-rose-400 italic">
          却下理由: {entry.dismissed_reason}
        </div>
      )}
      {snippet && (
        <details className="text-[10px] text-slate-300">
          <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
            yaml snippet (= プレビュー / 再コピー)
          </summary>
          <pre className="mt-1 p-2 bg-slate-950 rounded text-[10px] overflow-x-auto">
            {snippet}
          </pre>
          <button
            onClick={onCopySnippet}
            className="mt-1 text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-200 hover:bg-slate-700"
          >
            📋 再コピー
          </button>
        </details>
      )}
      {!isTerminal && (
        <div className="flex items-center gap-2 pt-1 flex-wrap">
          {entry.status === "new" && (
            <button
              disabled={busy}
              onClick={onMarkReviewing}
              className="text-[10px] px-2 py-0.5 rounded bg-amber-700/40 text-amber-100 border border-amber-600 hover:bg-amber-700/60 disabled:opacity-50"
            >
              ✏️ レビュー中にする
            </button>
          )}
          {(entry.status === "new" || entry.status === "reviewing") && (
            <>
              <button
                disabled={busy}
                onClick={onAccept}
                className="text-[10px] px-2 py-0.5 rounded bg-emerald-700/40 text-emerald-100 border border-emerald-600 hover:bg-emerald-700/60 disabled:opacity-50"
              >
                📋 yaml snippet 取得
              </button>
              <button
                disabled={busy}
                onClick={onDismiss}
                className="text-[10px] px-2 py-0.5 rounded bg-rose-700/40 text-rose-100 border border-rose-600 hover:bg-rose-700/60 disabled:opacity-50"
              >
                ❌ 却下
              </button>
            </>
          )}
          {entry.status === "accepted" && (
            <span className="text-[10px] text-emerald-300">
              ✅ accepted — yaml に貼り付けて PR を作成すると merged に遷移
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ───────────── clip_library entries ─────────────

function ClipLibrarySection() {
  const [data, setData] = useState<ClipsResponse | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    fetch(`/api/clips?status=${filter}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
        return r.json();
      })
      .then((d: ClipsResponse) => setData(d))
      .catch((e) => setError(String(e)));
  };
  useEffect(reload, [filter]);

  const onApprove = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      const r = await fetch(`/api/clips/${id}/approve`, { method: "POST" });
      if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
      reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };
  const onBlacklist = async (id: string) => {
    const reason = window.prompt("blacklist 理由 (任意):", "") ?? "";
    setBusy(id);
    setError(null);
    try {
      const r = await fetch(`/api/clips/${id}/blacklist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
      reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">📦 clip_library entries</h2>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">フィルタ:</span>
          {(["all", "active", "pending_review", "blacklisted"] as const).map(
            (s) => (
              <button
                key={s}
                className={
                  "px-2 py-0.5 rounded border text-[11px] " +
                  (filter === s
                    ? "bg-emerald-700/40 border-emerald-500 text-emerald-100"
                    : "bg-slate-800/40 border-slate-700 text-slate-400 hover:text-slate-200")
                }
                onClick={() => setFilter(s)}
              >
                {s}
              </button>
            ),
          )}
        </div>
      </div>
      {data && (
        <div className="text-xs text-slate-500">
          CLIP_LIBRARY_ENABLED ={" "}
          <span
            className={data.enabled ? "text-emerald-300" : "text-amber-300"}
          >
            {String(data.enabled)}
          </span>{" "}
          · 表示 {data.entries.length} 件
        </div>
      )}
      {error && <div className="text-xs text-rose-400">エラー: {error}</div>}
      {data && data.entries.length === 0 && (
        <div className="text-xs text-slate-500 italic">
          (該当 entry なし。Stage 3+4 で identity ありの screenplay を流すと
          cold path 完了時に register される)
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {(data?.entries ?? []).map((e) => (
          <ClipEntryCard
            key={e.id}
            entry={e}
            busy={busy === e.id}
            onApprove={() => onApprove(e.id)}
            onBlacklist={() => onBlacklist(e.id)}
          />
        ))}
      </div>
    </section>
  );
}

function ClipEntryCard({
  entry,
  busy,
  onApprove,
  onBlacklist,
}: {
  entry: ClipEntry;
  busy: boolean;
  onApprove: () => void;
  onBlacklist: () => void;
}) {
  const id = entry.identity;
  const ann = entry.annotation;
  const lc = entry.lifecycle;
  const statusColor =
    lc.status === "active"
      ? "bg-emerald-700/40 text-emerald-200"
      : lc.status === "pending_review"
        ? "bg-amber-700/40 text-amber-200"
        : "bg-rose-700/40 text-rose-200";
  return (
    <div className="border border-slate-800 rounded p-3 bg-slate-900/40 text-xs space-y-2">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] text-slate-500 truncate">
          {entry.id}
        </span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${statusColor}`}>
          {lc.status}
        </span>
        <span className="text-[10px] text-slate-500 ml-auto">
          hits: {lc.hit_count}
        </span>
      </div>
      <div className="text-[11px] text-slate-300">
        <span className="text-slate-500">identity:</span>{" "}
        {id.character_refs.join(",")} @ {id.location_ref} ({id.start_emotion},{" "}
        {id.camera_distance ?? "medium-close"})
      </div>
      {ann.visual_intent_id && (
        <div className="text-[11px] text-slate-400">
          <span className="text-slate-500">intent:</span> {ann.visual_intent_id}{" "}
          {ann.duration_bucket && `· ${ann.duration_bucket}s`}{" "}
          {ann.motion_intensity && `· ${ann.motion_intensity}`}
        </div>
      )}
      {entry.provenance.source_screenplay && (
        <div className="text-[10px] text-slate-500 truncate">
          source: {entry.provenance.source_screenplay} #
          {entry.provenance.source_scene_idx ?? "?"}
        </div>
      )}
      {lc.blacklist_reason && (
        <div className="text-[10px] text-rose-400 italic">
          理由: {lc.blacklist_reason}
        </div>
      )}
      <div className="flex items-center gap-2 pt-1">
        {lc.status !== "active" && (
          <button
            disabled={busy}
            onClick={onApprove}
            className="text-[10px] px-2 py-0.5 rounded bg-emerald-700/40 text-emerald-100 border border-emerald-600 hover:bg-emerald-700/60 disabled:opacity-50"
          >
            ✅ approve
          </button>
        )}
        {lc.status !== "blacklisted" && (
          <button
            disabled={busy}
            onClick={onBlacklist}
            className="text-[10px] px-2 py-0.5 rounded bg-rose-700/40 text-rose-100 border border-rose-600 hover:bg-rose-700/60 disabled:opacity-50"
          >
            🚫 blacklist
          </button>
        )}
      </div>
    </div>
  );
}

// ───────────── intent catalog ─────────────

function PartRegistrySection() {
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
