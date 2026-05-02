import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type {
  AnalyzeJobDetail,
  AnalyzePhase,
  AnalyzeStatus,
  DryrunCompleteEvent,
} from "../types";

const PHASE_LABELS: Record<AnalyzePhase, string> = {
  frames: "フレーム抽出",
  audio: "音声抽出",
  whisper: "文字起こし (Whisper)",
  acoustic: "音響特徴 (librosa)",
  bgm_detect: "BGM検出",
  shots: "ショット境界検出",
  bgm_separate: "BGM分離 (demucs)",
  claude: "Claude 分析 (Vision)",
  save: "台本保存",
};

const PHASE_HINTS: Record<AnalyzePhase, string> = {
  frames: "ffmpeg で動画から静止画を切り出し中",
  audio: "ffmpeg で 16kHz mono の音声トラックを抽出中",
  whisper:
    "Whisper で word 単位の文字起こしを生成中 (動画長依存、数秒〜数十秒)",
  acoustic: "librosa で各セグメントの pitch / RMS / wpm を抽出中",
  bgm_detect: "harmonic/percussive 分離で BGM 有無を判定中",
  shots: "PySceneDetect でショット境界を検出中",
  bgm_separate: "demucs / HPSS で BGM トラックを分離中 (時間がかかる場合あり)",
  claude: "Claude Opus 4.7 にフレーム+音声情報を送って台本生成中",
  save: "screenplay JSON を screenplays/auto_*.json に書き出し中",
};

const STATUS_LABELS: Record<AnalyzeStatus, string> = {
  pending: "待機中",
  dryrunning: "ドライラン中",
  awaiting_confirm: "コスト確認待ち",
  running: "実行中",
  completed: "完了",
  failed: "失敗",
  cancelled: "キャンセル済み",
};

const TERMINAL: AnalyzeStatus[] = ["completed", "failed", "cancelled"];

interface PhaseState {
  phase: AnalyzePhase;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  durationMs: number | null;
  fromCache: boolean;
  message?: string;
}

const PHASE_ORDER: AnalyzePhase[] = [
  "frames",
  "audio",
  "whisper",
  "acoustic",
  "bgm_detect",
  "shots",
  "bgm_separate",
  "claude",
  "save",
];

function formatDuration(ms: number): string {
  if (ms < 0) ms = 0;
  const totalSec = ms / 1000;
  if (totalSec < 60) return `${totalSec.toFixed(1)}s`;
  const m = Math.floor(totalSec / 60);
  const s = Math.floor(totalSec % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export default function AnalyzeJobView({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<AnalyzeJobDetail | null>(null);
  const [phases, setPhases] = useState<Record<AnalyzePhase, PhaseState>>(
    () =>
      Object.fromEntries(
        PHASE_ORDER.map((p) => [
          p,
          { phase: p, status: "pending", durationMs: null, fromCache: false },
        ]),
      ) as Record<AnalyzePhase, PhaseState>,
  );
  const [phaseStartTimes, setPhaseStartTimes] = useState<
    Partial<Record<AnalyzePhase, number>>
  >({});
  const [dryrun, setDryrun] = useState<DryrunCompleteEvent | null>(null);
  const [completedPath, setCompletedPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [now, setNow] = useState<number>(Date.now());
  const [claudeChars, setClaudeChars] = useState<number>(0);
  const esRef = useRef<EventSource | null>(null);

  // 初回詳細ロード
  useEffect(() => {
    api
      .getAnalyzeJob(jobId)
      .then((d) => {
        setJob(d);
        setPhases((prev) => {
          const next = { ...prev };
          for (const p of d.phases) {
            next[p.phase] = {
              phase: p.phase,
              status: p.status,
              durationMs: p.duration_ms,
              fromCache: false,
            };
          }
          return next;
        });
        if (d.estimated_cost_usd !== null && d.status === "awaiting_confirm") {
          setDryrun({
            frame_count: 0,
            input_tokens: 0,
            output_tokens: 0,
            cost_usd: d.estimated_cost_usd,
            cost_breakdown: {},
          });
        }
        if (d.screenplay_path) setCompletedPath(d.screenplay_path);
        if (d.error) setError(d.error);
      })
      .catch((e) => setError(String(e)));
  }, [jobId]);

  // SSE 接続
  useEffect(() => {
    const es = api.analyzeJobEventSource(jobId);
    esRef.current = es;

    const handlePhase = (phase: AnalyzePhase, partial: Partial<PhaseState>) => {
      setPhases((prev) => ({
        ...prev,
        [phase]: { ...prev[phase], ...partial, phase },
      }));
    };

    es.addEventListener("state", (ev) => {
      try {
        const d = JSON.parse((ev as MessageEvent).data);
        setJob((prev) => (prev ? { ...prev, ...d } : prev));
      } catch {}
    });
    es.addEventListener("phase_start", (ev) => {
      try {
        const d = JSON.parse((ev as MessageEvent).data);
        if (d.phase) {
          handlePhase(d.phase, { status: "running" });
          setPhaseStartTimes((prev) => ({ ...prev, [d.phase]: Date.now() }));
          if (d.phase === "claude") setClaudeChars(0);
        }
      } catch {}
    });
    es.addEventListener("phase_complete", (ev) => {
      try {
        const d = JSON.parse((ev as MessageEvent).data);
        if (d.phase)
          handlePhase(d.phase, {
            status: "completed",
            durationMs:
              typeof d.duration_ms === "number" ? d.duration_ms : null,
            fromCache: !!d.from_cache,
            message: d.skipped_reason || undefined,
          });
      } catch {}
    });
    es.addEventListener("phase_skipped", (ev) => {
      try {
        const d = JSON.parse((ev as MessageEvent).data);
        if (d.phase)
          handlePhase(d.phase, {
            status: "skipped",
            message: d.reason || "スキップ",
          });
      } catch {}
    });
    es.addEventListener("dryrun_complete", (ev) => {
      try {
        setDryrun(JSON.parse((ev as MessageEvent).data));
      } catch {}
    });
    es.addEventListener("claude_chunk", (ev) => {
      try {
        const d = JSON.parse((ev as MessageEvent).data);
        if (typeof d.delta === "string") {
          setClaudeChars((prev) => prev + d.delta.length);
        }
      } catch {}
    });
    es.addEventListener("completed", (ev) => {
      try {
        const d = JSON.parse((ev as MessageEvent).data);
        if (d.output_path) setCompletedPath(d.output_path);
        setJob((prev) =>
          prev
            ? { ...prev, status: "completed", screenplay_path: d.output_path }
            : prev,
        );
        es.close();
      } catch {}
    });
    es.addEventListener("failed", (ev) => {
      try {
        const d = JSON.parse((ev as MessageEvent).data);
        setError(d.error || "failed");
        setJob((prev) =>
          prev ? { ...prev, status: "failed", error: d.error } : prev,
        );
        es.close();
      } catch {}
    });
    es.addEventListener("cancelled", () => {
      setJob((prev) => (prev ? { ...prev, status: "cancelled" } : prev));
      es.close();
    });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) return;
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [jobId]);

  // リアルタイム時計 (ジョブ実行中のみ更新)
  const isTerminal = job ? TERMINAL.includes(job.status) : false;
  useEffect(() => {
    if (!job || isTerminal) return;
    const id = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(id);
  }, [job?.status, isTerminal, job]);

  // 集計
  const { completedCount, totalCount, overallPct } = useMemo(() => {
    const total = PHASE_ORDER.length;
    const done = PHASE_ORDER.filter(
      (p) => phases[p].status === "completed" || phases[p].status === "skipped",
    ).length;
    return {
      completedCount: done,
      totalCount: total,
      overallPct: (done / total) * 100,
    };
  }, [phases]);

  const jobStartedAt = useMemo(() => {
    if (!job?.started_at) return null;
    const t = new Date(job.started_at).getTime();
    return Number.isNaN(t) ? null : t;
  }, [job?.started_at]);

  const jobFinishedAt = useMemo(() => {
    if (!job?.finished_at) return null;
    const t = new Date(job.finished_at).getTime();
    return Number.isNaN(t) ? null : t;
  }, [job?.finished_at]);

  const overallElapsedMs = useMemo(() => {
    if (!jobStartedAt) return 0;
    const end = jobFinishedAt ?? now;
    return end - jobStartedAt;
  }, [jobStartedAt, jobFinishedAt, now]);

  const currentPhase = job?.current_phase ?? null;
  const currentPhaseElapsedMs = useMemo(() => {
    if (!currentPhase) return 0;
    const start = phaseStartTimes[currentPhase];
    if (!start) return 0;
    return now - start;
  }, [currentPhase, phaseStartTimes, now]);

  if (!job) return <div className="text-sm text-slate-400">読み込み中...</div>;

  const screenplayName = completedPath
    ? completedPath
        .split("/")
        .pop()
        ?.replace(/\.json$/, "")
    : null;

  // プログレスバーの色
  const barColor =
    job.status === "failed"
      ? "bg-rose-500"
      : job.status === "cancelled"
        ? "bg-slate-500"
        : job.status === "completed"
          ? "bg-emerald-500"
          : "bg-emerald-600";

  const showCurrentPhasePanel =
    currentPhase && (job.status === "running" || job.status === "dryrunning");

  return (
    <div className="space-y-4">
      {/* ─── ヘッダー (ID + status + キャンセル) ──────────── */}
      <div className="card">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-400 font-mono">{job.id}</div>
            <div className="text-sm">
              status:{" "}
              <span className="font-mono">{STATUS_LABELS[job.status]}</span>
            </div>
          </div>
          {!isTerminal && (
            <button
              className="btn-ghost text-xs"
              onClick={async () => {
                if (!confirm("ジョブをキャンセルしますか?")) return;
                try {
                  await api.cancelAnalyzeJob(jobId);
                } catch (e) {
                  setError(String(e));
                }
              }}
            >
              キャンセル
            </button>
          )}
        </div>
        {error && (
          <div className="mt-2 text-sm text-rose-300 whitespace-pre-wrap">
            error: {error}
          </div>
        )}
      </div>

      {/* ─── 全体プログレスバー ─────────────────────────── */}
      <div className="card">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold">全体進捗</h3>
          <div className="text-xs text-slate-400 font-mono">
            {jobStartedAt
              ? `経過 ${formatDuration(overallElapsedMs)}`
              : "未開始"}
          </div>
        </div>
        <div className="h-3 w-full rounded bg-slate-700 overflow-hidden">
          <div
            className={`h-full ${barColor} transition-all duration-300`}
            style={{ width: `${overallPct}%` }}
          />
        </div>
        <div className="mt-1 text-xs text-slate-400 flex justify-between">
          <span>
            {completedCount} / {totalCount} フェーズ完了
          </span>
          <span className="font-mono">{Math.round(overallPct)}%</span>
        </div>
      </div>

      {/* ─── 現在実行中フェーズ強調 ────────────────────── */}
      {showCurrentPhasePanel && currentPhase && (
        <div className="card border border-amber-500/40 bg-amber-900/10">
          <div className="text-xs text-amber-400 mb-1">⏱ 現在実行中</div>
          <div className="flex items-start gap-3">
            <div className="text-amber-300 text-2xl animate-pulse leading-none">
              ▶
            </div>
            <div className="flex-1">
              <div className="text-base font-semibold text-amber-100">
                {PHASE_LABELS[currentPhase]}
              </div>
              <div className="text-xs text-slate-400 mt-1">
                {PHASE_HINTS[currentPhase]}
              </div>
              <div className="text-xs text-slate-400 mt-2 font-mono">
                このフェーズ: {formatDuration(currentPhaseElapsedMs)}
              </div>
              {currentPhase === "claude" && claudeChars > 0 && (
                <div className="text-xs text-emerald-300 mt-1">
                  Claude が生成中... ({claudeChars.toLocaleString()} 文字)
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ─── フェーズ詳細 (タイムライン) ────────────────── */}
      <div className="card">
        <h3 className="font-semibold mb-2">フェーズ詳細</h3>
        <ol className="space-y-1 text-sm">
          {PHASE_ORDER.map((p) => {
            const st = phases[p];
            const isCurrent = currentPhase === p && !isTerminal;
            const color =
              st.status === "completed"
                ? "text-emerald-300"
                : st.status === "running"
                  ? "text-amber-300"
                  : st.status === "failed"
                    ? "text-rose-300"
                    : st.status === "skipped"
                      ? "text-slate-500"
                      : "text-slate-400";
            const icon =
              st.status === "completed"
                ? "✓"
                : st.status === "running"
                  ? "▶"
                  : st.status === "failed"
                    ? "✗"
                    : st.status === "skipped"
                      ? "—"
                      : "·";
            return (
              <li
                key={p}
                className={`${color} ${isCurrent ? "font-semibold" : ""}`}
              >
                <span className="font-mono mr-2">{icon}</span>
                {PHASE_LABELS[p]}
                {st.fromCache && (
                  <span className="ml-2 text-xs text-slate-500">(cache)</span>
                )}
                {st.durationMs != null && (
                  <span className="ml-2 text-xs text-slate-500 font-mono">
                    {(st.durationMs / 1000).toFixed(2)}s
                  </span>
                )}
                {isCurrent && (
                  <span className="ml-2 text-xs text-amber-400 font-mono">
                    {formatDuration(currentPhaseElapsedMs)}
                  </span>
                )}
                {st.message && (
                  <span className="ml-2 text-xs text-slate-500">
                    {st.message}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      {/* ─── コストゲート モーダル ──────────────────────── */}
      {dryrun && job.status === "awaiting_confirm" && (
        <div className="card border border-amber-500/40">
          <h3 className="font-semibold mb-2 text-amber-300">
            ⚠ Claude 呼び出しの確認
          </h3>
          <div className="text-sm space-y-1">
            <div>
              フレーム数:{" "}
              <span className="font-mono">{dryrun.frame_count}</span>
            </div>
            <div>
              推定 input tokens:{" "}
              <span className="font-mono">
                {dryrun.input_tokens?.toLocaleString()}
              </span>
            </div>
            <div>
              推定 output tokens:{" "}
              <span className="font-mono">
                {dryrun.output_tokens?.toLocaleString()}
              </span>
            </div>
            <div>
              推定コスト:{" "}
              <span className="font-mono text-amber-300">
                ${dryrun.cost_usd?.toFixed(3)}
              </span>
              <span className="ml-2 text-xs text-slate-400">
                (≈ ¥{Math.round((dryrun.cost_usd ?? 0) * 150)})
              </span>
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <button
              className="btn-primary"
              onClick={async () => {
                setConfirmBusy(true);
                try {
                  await api.confirmAnalyzeJob(jobId);
                } catch (e) {
                  setError(String(e));
                } finally {
                  setConfirmBusy(false);
                }
              }}
              disabled={confirmBusy}
            >
              {confirmBusy ? "..." : "Claude 呼び出しを許可"}
            </button>
            <button
              className="btn-ghost"
              onClick={async () => {
                if (!confirm("ジョブをキャンセルしますか?")) return;
                try {
                  await api.cancelAnalyzeJob(jobId);
                } catch (e) {
                  setError(String(e));
                }
              }}
            >
              キャンセル
            </button>
          </div>
        </div>
      )}

      {/* ─── 完了時のサマリ + リンク ────────────────────── */}
      {completedPath && screenplayName && (
        <div className="card border border-emerald-500/40">
          <h3 className="font-semibold mb-2 text-emerald-300">✓ 分析完了</h3>
          <div className="text-sm">
            生成台本:{" "}
            <span className="font-mono break-all">{completedPath}</span>
          </div>
          {jobStartedAt && jobFinishedAt && (
            <div className="text-xs text-slate-400 mt-1">
              総所要時間: {formatDuration(jobFinishedAt - jobStartedAt)}
            </div>
          )}
          <div className="mt-3">
            <Link to="/" className="btn-primary">
              プロジェクト一覧へ ({screenplayName} で新規プロジェクト)
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
