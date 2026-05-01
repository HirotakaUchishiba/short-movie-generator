import { useEffect, useRef, useState } from "react";
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
  whisper: "文字起こし",
  acoustic: "音響特徴",
  bgm_detect: "BGM検出",
  shots: "ショット境界",
  bgm_separate: "BGM分離",
  claude: "Claude分析",
  save: "保存",
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
  const [dryrun, setDryrun] = useState<DryrunCompleteEvent | null>(null);
  const [completedPath, setCompletedPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  // 初回詳細ロード
  useEffect(() => {
    api
      .getAnalyzeJob(jobId)
      .then((d) => {
        setJob(d);
        // phases を SQLite の状態で初期化
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
        if (d.phase) handlePhase(d.phase, { status: "running" });
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
      // 自然な接続終了 (terminal event 後の close など) は無視
      if (es.readyState === EventSource.CLOSED) return;
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [jobId]);

  const onConfirm = async () => {
    setConfirmBusy(true);
    try {
      await api.confirmAnalyzeJob(jobId);
    } catch (e) {
      setError(String(e));
    } finally {
      setConfirmBusy(false);
    }
  };

  const onCancel = async () => {
    if (!confirm("ジョブをキャンセルしますか?")) return;
    try {
      await api.cancelAnalyzeJob(jobId);
    } catch (e) {
      setError(String(e));
    }
  };

  if (!job) return <div className="text-sm text-slate-400">読み込み中...</div>;

  const isTerminal = TERMINAL.includes(job.status);
  const screenplayName = completedPath
    ? completedPath
        .split("/")
        .pop()
        ?.replace(/\.json$/, "")
    : null;

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-400">{job.id}</div>
            <div className="text-sm">
              status:{" "}
              <span className="font-mono">{STATUS_LABELS[job.status]}</span>
              {job.current_phase && job.status === "running" && (
                <>
                  {" "}
                  · phase:{" "}
                  <span className="font-mono">
                    {PHASE_LABELS[job.current_phase]}
                  </span>
                </>
              )}
            </div>
          </div>
          {!isTerminal && (
            <button className="btn-ghost text-xs" onClick={onCancel}>
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

      <div className="card">
        <h3 className="font-semibold mb-2">フェーズ進捗</h3>
        <ol className="space-y-1 text-sm">
          {PHASE_ORDER.map((p) => {
            const st = phases[p];
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
              <li key={p} className={color}>
                <span className="font-mono mr-2">{icon}</span>
                {PHASE_LABELS[p]}
                {st.fromCache && (
                  <span className="ml-2 text-xs text-slate-500">(cache)</span>
                )}
                {st.durationMs != null && (
                  <span className="ml-2 text-xs text-slate-500">
                    {(st.durationMs / 1000).toFixed(2)}s
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

      {dryrun && job.status === "awaiting_confirm" && (
        <div className="card border border-amber-500/40">
          <h3 className="font-semibold mb-2 text-amber-300">コスト確認</h3>
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
              onClick={onConfirm}
              disabled={confirmBusy}
            >
              {confirmBusy ? "..." : "Claude 呼び出しを許可"}
            </button>
            <button className="btn-ghost" onClick={onCancel}>
              キャンセル
            </button>
          </div>
        </div>
      )}

      {completedPath && screenplayName && (
        <div className="card border border-emerald-500/40">
          <h3 className="font-semibold mb-2 text-emerald-300">分析完了</h3>
          <div className="text-sm">
            生成台本:{" "}
            <span className="font-mono break-all">{completedPath}</span>
          </div>
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
