import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { usePartCatalog } from "../hooks/usePartCatalog";

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
 *   1. Library 状態 (= CLIP_LIBRARY_ENABLED の env / pool 数概要)
 *   2. clip_library entry の一覧 + 承認 / blacklist 操作
 *   3. part_registry catalog の閲覧 (= 各 category の利用可能 id を確認)
 *
 * 設計 ref: docs/plannings/2026-05-10_compositional-architecture.md §3-4
 */
export default function IntentCatalogPage() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <header className="px-6 py-4 border-b border-slate-800 flex items-center gap-4">
        <Link to="/" className="text-sm text-slate-400 hover:text-emerald-300">
          ← プロジェクト一覧
        </Link>
        <h1 className="text-lg font-semibold">
          🗂 Intent Catalog (= clip_library + part_registry 運用)
        </h1>
      </header>
      <div className="max-w-6xl mx-auto p-6 space-y-8">
        <ClipLibrarySection />
        <PartRegistrySection />
      </div>
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

// ───────────── part_registry catalog ─────────────

function PartRegistrySection() {
  const state = usePartCatalog();
  if (state.kind === "loading") {
    return (
      <section className="text-xs text-slate-500">
        part_registry を取得中…
      </section>
    );
  }
  if (state.kind === "error") {
    return (
      <section className="text-xs text-rose-400">
        part_registry エラー: {state.message}
      </section>
    );
  }
  const cats = state.data.categories;
  return (
    <section className="space-y-3">
      <h2 className="text-base font-semibold">
        🎨 part_registry (= 利用可能パーツ)
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {Object.entries(cats).map(([catName, catData]) => (
          <div
            key={catName}
            className="border border-slate-800 rounded p-3 bg-slate-900/40 text-xs space-y-1"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-[11px] text-emerald-300">
                {catName}
              </span>
              <span className="text-[10px] text-slate-500">
                {catData.entries.length} entries
              </span>
            </div>
            {!catData.found && (
              <div className="text-[10px] text-rose-400">
                yaml が見つからない (= /api/parts/catalog の find:false)
              </div>
            )}
            <ul className="space-y-0.5">
              {catData.entries.map((entry) => (
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
        ))}
      </div>
    </section>
  );
}
