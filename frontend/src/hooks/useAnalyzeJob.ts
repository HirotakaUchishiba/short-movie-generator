// AnalyzeJobView.tsx から抽出した状態管理 hook (= §3.1.3 / §3.3 巨大関数分解)。
//
// analyze job の SSE 購読 + phase 進捗 + cost gate confirm / cancel action を
// すべて閉じ込める。AnalyzeJobView は本 hook の戻り値を render するだけの
// presentation コンポーネントになる。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError } from "../api";
import type {
  AnalyzeJobDetail,
  AnalyzePhase,
  DryrunCompleteEvent,
} from "../types";
import { PHASE_ORDER, TERMINAL } from "../components/analyze-job-utils";

export interface PhaseState {
  phase: AnalyzePhase;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  durationMs: number | null;
  fromCache: boolean;
  message?: string;
}

export interface AnnotationStats {
  total_scenes: number;
  with_visual_intent_id: number;
  low_confidence_demoted: number;
  by_intent_id: Record<string, number>;
}

export interface SuggestedIntent {
  proposed_id: string;
  description: string;
  scene_indices: number[];
  rationale: string;
}

export function useAnalyzeJob(jobId: string) {
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
  const [annotationStats, setAnnotationStats] =
    useState<AnnotationStats | null>(null);
  const [suggestedIntents, setSuggestedIntents] = useState<SuggestedIntent[]>(
    [],
  );
  const esRef = useRef<EventSource | null>(null);

  // 初回詳細ロード
  useEffect(() => {
    let cancelled = false;
    api
      .getAnalyzeJob(jobId)
      .then((d) => {
        if (cancelled) return;
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
        if (d.status === "awaiting_confirm") {
          // estimated_cost_usd が null (= 履歴不足) でも dryrun は復元する。
          // モーダルを出さないと SSE を受け損ねた / リロード時に Claude 呼び出しを
          // 再開できなくなるため。confidence は cost の有無で出し分け。
          setDryrun({
            frame_count: 0,
            input_tokens: 0,
            output_tokens: 0,
            cost_usd: d.estimated_cost_usd,
            cost_jpy: null,
            confidence:
              d.estimated_cost_usd == null ? "insufficient" : "history",
            sample_size: 0,
          });
        }
        if (d.screenplay_path) setCompletedPath(d.screenplay_path);
        if (d.error) setError(d.error);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
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
          // claude phase 開始 = cost gate 通過後なので job.status は running。
          // confirm 成功時の UI 更新が遅れた場合の保険として同期する。
          setJob((prev) =>
            prev && prev.status === "awaiting_confirm"
              ? { ...prev, status: "running" }
              : prev,
          );
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
        // save phase に annotation_stats が乗っていれば UI 表示用に取り込む
        if (d.phase === "save" && d.annotation_stats) {
          const s = d.annotation_stats as Partial<AnnotationStats>;
          if (
            typeof s.total_scenes === "number" &&
            typeof s.with_visual_intent_id === "number" &&
            typeof s.low_confidence_demoted === "number"
          ) {
            setAnnotationStats({
              total_scenes: s.total_scenes,
              with_visual_intent_id: s.with_visual_intent_id,
              low_confidence_demoted: s.low_confidence_demoted,
              by_intent_id: (s.by_intent_id as Record<string, number>) ?? {},
            });
          }
        }
        // 設計 §8.2: novel intent 候補が乗っていれば取り込む (= 空 list でも上書き)
        if (d.phase === "save" && Array.isArray(d.suggested_intents)) {
          const items = (d.suggested_intents as unknown[]).filter(
            (x): x is SuggestedIntent => {
              if (!x || typeof x !== "object") return false;
              const o = x as Record<string, unknown>;
              return (
                typeof o.proposed_id === "string" &&
                typeof o.description === "string" &&
                Array.isArray(o.scene_indices) &&
                typeof o.rationale === "string"
              );
            },
          );
          setSuggestedIntents(items);
        }
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
        // SSE では status 遷移そのものは publish されないため、
        // dryrun_complete を受けたら awaiting_confirm に明示的に切り替えて
        // コスト確認モーダルを表示する (これがないとモーダルが永遠に出ない)。
        setJob((prev) =>
          prev ? { ...prev, status: "awaiting_confirm" } : prev,
        );
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
  const jobAbsent = !job;
  useEffect(() => {
    if (jobAbsent || isTerminal) return;
    const id = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(id);
  }, [jobAbsent, isTerminal]);

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

  // ─── actions (= cost gate confirm / cancel) ──────────
  const confirmCostGate = useCallback(async () => {
    setConfirmBusy(true);
    try {
      await api.confirmAnalyzeJob(jobId);
      // 成功: サーバが running に遷移済み。UI も同期してモーダルを閉じる。
      setJob((prev) => (prev ? { ...prev, status: "running" } : prev));
      setDryrun(null);
      setError(null);
    } catch (e) {
      // 既に running / 既に terminal (= dryrun 二重クリック等) の状態遷移エラーは
      // 実害なし。backend は error_code = "ANALYZE_JOB_INVALID_STATE" を返すので
      // それで判定 (= status 単独より具体的)。
      if (
        e instanceof ApiError &&
        e.status === 409 &&
        (e.body as { error_code?: string } | null)?.error_code ===
          "ANALYZE_JOB_INVALID_STATE"
      ) {
        setJob((prev) => (prev ? { ...prev, status: "running" } : prev));
        setDryrun(null);
        setError(null);
      } else {
        setError(String(e));
      }
    } finally {
      setConfirmBusy(false);
    }
  }, [jobId]);

  const cancelJob = useCallback(async () => {
    try {
      await api.cancelAnalyzeJob(jobId);
    } catch (e) {
      setError(String(e));
    }
  }, [jobId]);

  return {
    job,
    phases,
    now,
    dryrun,
    completedPath,
    error,
    confirmBusy,
    claudeChars,
    annotationStats,
    suggestedIntents,
    isTerminal,
    completedCount,
    totalCount,
    overallPct,
    jobStartedAt,
    jobFinishedAt,
    overallElapsedMs,
    currentPhase,
    currentPhaseElapsedMs,
    confirmCostGate,
    cancelJob,
  };
}
