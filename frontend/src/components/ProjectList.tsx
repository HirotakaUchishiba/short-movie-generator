import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, bgAssetUrl } from "../api";
import type {
  ProjectListItem,
  Progress,
  StageErrorDetail,
  StageName,
} from "../types";
import CreateFromReferenceVideoSection from "./CreateFromReferenceVideoSection";
import { DeleteProjectButton } from "./common/DeleteProjectButton";

const STAGE_LABELS: Record<StageName, string> = {
  script: "台本",
  tts: "TTS",
  bg: "背景",
  kling: "Kling",
  scene: "音声合成",
  overlay: "字幕",
  final_import: "取込",
  publish: "公開",
};

// stage の中で status==="failed" のものを探し、tooltip 用に actionable_hint を返す。
// analyze (= Stage 0) も対象に含めるため StageName ではなく string 走査。
function findFailedStageTooltip(progress: Progress | undefined): string | null {
  if (!progress?.stages) return null;
  const order = [
    "analyze",
    "script",
    "tts",
    "bg",
    "kling",
    "scene",
    "overlay",
    "final_import",
    "publish",
  ];
  for (const stage of order) {
    const block = (progress.stages as Record<string, unknown>)[stage] as
      | { status?: string; error_detail?: StageErrorDetail }
      | undefined;
    if (block?.status === "failed" && block.error_detail) {
      const d = block.error_detail;
      const stageLabel = STAGE_LABELS[stage as StageName] ?? stage;
      const hint = d.actionable_hint ? `\n${d.actionable_hint}` : "";
      return `${stageLabel}: ${d.type}${hint}`;
    }
  }
  return null;
}

function formatCreatedAt(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const m = d.getMonth() + 1;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${m}/${day} ${hh}:${mm}`;
}

// 「分析失敗」状態の project を集めて bulk delete する header button。
// 0 件なら何も render しない。bulk-delete API の partial-success に対応し、
// 失敗 ts がある場合は inline error として表示する。
function BulkDeleteFailedButton({
  projects,
  onDeleted,
}: {
  projects: ProjectListItem[];
  onDeleted: () => void;
}) {
  const failed = projects.filter((p) => p.analyze_status === "failed");
  const [busy, setBusy] = useState(false);
  const [partialError, setPartialError] = useState<string | null>(null);

  if (failed.length === 0) return null;

  const onClick = async () => {
    if (
      !window.confirm(
        `分析失敗プロジェクト ${failed.length} 件を削除しますか?\n\n` +
          "各プロジェクトの temp/<TS>/ ディレクトリを削除します。\n" +
          "参考動画 / 分析履歴 / 投稿履歴は保持されます。",
      )
    ) {
      return;
    }
    setBusy(true);
    setPartialError(null);
    try {
      const tsList = failed.map((p) => p.timestamp);
      const r = await api.bulkDeleteProjects(tsList);
      if (r.failed.length > 0) {
        setPartialError(
          `${r.failed.length} 件失敗: ` +
            r.failed
              .map((f) => `${f.ts} (${f.error_code})`)
              .slice(0, 5)
              .join(", ") +
            (r.failed.length > 5 ? " ..." : ""),
        );
      }
      onDeleted();
    } catch (e) {
      setPartialError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-baseline gap-2">
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className="rounded bg-rose-600/90 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
        data-testid="bulk-delete-failed"
      >
        {busy ? "削除中..." : `⚠ 分析失敗 ${failed.length} 件をまとめて削除`}
      </button>
      {partialError && (
        <span className="text-xs text-rose-300" data-testid="bulk-delete-error">
          {partialError}
        </span>
      )}
    </div>
  );
}

function ProjectCard({
  p,
  onDeleted,
}: {
  p: ProjectListItem;
  onDeleted: (ts: string) => void;
}) {
  const stageLabel = p.current_stage
    ? (STAGE_LABELS[p.current_stage] ?? p.current_stage)
    : "完了";
  const isDone = !p.current_stage;
  const isAnalyzing =
    p.analyze_status === "running" || p.analyze_status === "pending";
  const analyzeFailed = p.analyze_status === "failed";
  const failureTooltip = findFailedStageTooltip(p.progress);
  const isFailed = analyzeFailed || failureTooltip !== null;
  // Stage 0 中 / 失敗の project は専用 page (= /project/<TS>/analyze) へ。
  // それ以外 (= Stage 1+ または legacy 経路) は通常の ProjectShell へ。
  const linkTo =
    isAnalyzing || analyzeFailed
      ? `/project/${p.timestamp}/analyze`
      : `/project/${p.timestamp}`;
  return (
    <Link
      to={linkTo}
      className="group flex flex-col overflow-hidden rounded-lg border border-slate-700 bg-slate-800/50 transition hover:border-emerald-400 hover:bg-slate-800"
    >
      <div className="relative aspect-[9/16] overflow-hidden bg-slate-900">
        {p.has_bg_thumbnail ? (
          <img
            src={bgAssetUrl(p.timestamp, 0)}
            alt=""
            className="h-full w-full object-cover transition group-hover:scale-[1.02]"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center text-slate-600">
            <svg
              className="h-10 w-10"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3.75 6.75A2.25 2.25 0 016 4.5h12a2.25 2.25 0 012.25 2.25v10.5A2.25 2.25 0 0118 19.5H6a2.25 2.25 0 01-2.25-2.25V6.75z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9.75 10.5l3.75 4.5 2.25-2.625L19.5 16.5"
              />
            </svg>
            <span className="mt-2 text-xs">背景未生成</span>
          </div>
        )}
        <div className="absolute left-2 top-2">
          {isAnalyzing ? (
            <span className="badge bg-amber-600/90 text-white">📹 分析中</span>
          ) : analyzeFailed ? (
            <span
              className="badge bg-rose-600/90 text-white"
              title={failureTooltip ?? undefined}
            >
              ⚠ 分析失敗
            </span>
          ) : failureTooltip ? (
            <span
              className="badge bg-rose-600/90 text-white"
              title={failureTooltip}
            >
              ⚠ {stageLabel} 失敗
            </span>
          ) : (
            <span
              className={
                "badge " +
                (isDone
                  ? "bg-emerald-600/90 text-white"
                  : "bg-slate-900/80 text-slate-100 backdrop-blur")
              }
            >
              {isDone ? "✓ " : ""}
              {stageLabel}
            </span>
          )}
        </div>
        {p.scene_count > 0 && (
          <div className="absolute bottom-2 right-2">
            <span className="badge bg-slate-900/80 text-slate-200 backdrop-blur">
              {p.scene_count}シーン
            </span>
          </div>
        )}
        {/* 削除ボタン: 失敗プロジェクトは常時表示 (= 目立つ rose 色)、
            それ以外は hover で出る icon mode。Link 内なので button 側で
            preventDefault + stopPropagation を呼ぶ。 */}
        <div
          className={
            "absolute right-2 top-2 transition-opacity " +
            (isFailed ? "opacity-100" : "opacity-0 group-hover:opacity-100")
          }
        >
          <DeleteProjectButton
            ts={p.timestamp}
            titleHint={p.display_title}
            onDeleted={onDeleted}
            mode={isFailed ? "label" : "icon"}
          />
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div
          className="line-clamp-2 text-sm font-semibold leading-snug"
          title={p.display_title}
        >
          {p.display_title}
        </div>
        {p.caption_hashtags && (
          <div
            className="line-clamp-1 text-xs text-emerald-400/80"
            title={p.caption_hashtags}
          >
            {p.caption_hashtags}
          </div>
        )}
        <div className="mt-auto text-[11px] text-slate-500">
          {formatCreatedAt(p.created_at)}
        </div>
      </div>
    </Link>
  );
}

export default function ProjectList() {
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [screenplays, setScreenplays] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [selectedScreenplay, setSelectedScreenplay] = useState("");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.projects();
      setProjects(r.projects);
      setScreenplays(r.screenplays);
      setSelectedScreenplay((prev) => prev || r.screenplays[0] || "");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onCreate = async () => {
    if (!selectedScreenplay) return;
    setCreating(true);
    setError(null);
    try {
      const r = await api.createProject(selectedScreenplay);
      navigate(`/project/${r.timestamp}/script`);
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl p-8">
      <header className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="mb-2 text-3xl font-bold">short movie generator</h1>
          <p className="text-sm text-slate-400">
            段階的ゲート方式で動画を生成。各stageで人間が確認・承認してから次に進めます。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/intent-catalog"
            className="btn-ghost whitespace-nowrap text-sm"
            title="clip_library entry の承認 / blacklist + part_registry の閲覧"
          >
            🗂 Intent Catalog →
          </Link>
        </div>
      </header>

      {error && (
        <div className="mb-4 rounded border border-rose-700 bg-rose-900/40 p-3 text-sm">
          {error}
        </div>
      )}

      {/* 主動作: 参考動画から作成 (= Phase C の主導フロー CTA) */}
      <CreateFromReferenceVideoSection
        onSuccess={(ts) => navigate(`/project/${ts}/analyze`)}
      />

      {/* 副動作: 既存 template から作成 (= 量産・再利用ユーザー向け、折りたたみ) */}
      <details className="card mb-8" data-testid="legacy-template-section">
        <summary className="cursor-pointer text-sm text-slate-400 hover:text-slate-200">
          既存 template から作成 (= analyze 済み auto_*.json から再生成)
        </summary>
        <div className="mt-3 flex items-center gap-3">
          <select
            className="input flex-1"
            value={selectedScreenplay}
            onChange={(e) => setSelectedScreenplay(e.target.value)}
          >
            {screenplays.length === 0 && (
              <option value="">台本がありません</option>
            )}
            {screenplays.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            className="btn-secondary"
            disabled={!selectedScreenplay || creating}
            onClick={onCreate}
          >
            {creating ? "作成中..." : "プロジェクト作成"}
          </button>
        </div>
      </details>

      <section>
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold">既存プロジェクト</h2>
          <div className="flex items-baseline gap-3">
            <BulkDeleteFailedButton
              projects={projects}
              onDeleted={() => void reload()}
            />
            {!loading && projects.length > 0 && (
              <span className="text-xs text-slate-500">
                {projects.length}件
              </span>
            )}
          </div>
        </div>
        {loading && <p className="text-slate-400">読み込み中...</p>}
        {!loading && projects.length === 0 && (
          <p className="text-slate-400">プロジェクトがありません</p>
        )}
        {!loading && projects.length > 0 && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {projects.map((p) => (
              <ProjectCard
                key={p.timestamp}
                p={p}
                onDeleted={() => void reload()}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
