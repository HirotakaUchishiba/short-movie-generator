import { useOutletContext } from "react-router-dom";
import { useState } from "react";
import type { StageName } from "../types";
import type { ReactNode } from "react";
import RejectModal from "./RejectModal";

interface ShellCtx {
  detail: {
    progress: {
      stages: Record<
        StageName,
        {
          generated_at: string | null;
          approved_at: string | null;
          regen_count: number;
        }
      >;
    };
  };
  approveCurrent: (stage: StageName) => Promise<void>;
  runNext: () => Promise<void>;
  jobStatus: { status: string } | null;
}

export function useShellCtx() {
  return useOutletContext() as ShellCtx & {
    detail: import("../types").ProjectDetail;
    serverConfig: import("../types").ServerConfig;
    reload: () => Promise<void>;
    reloadConfig: () => Promise<void>;
    regen: (body: {
      stage: StageName;
      scene_idx?: number;
      line_idx?: number;
      force?: boolean;
      force_no_cache?: boolean;
    }) => Promise<void>;
    jobStatus: import("../types").JobStatus | null;
  };
}

export default function StageGate({
  stage,
  title,
  description,
  children,
  needsRunFirst = false,
}: {
  stage: StageName;
  title: string;
  description?: string;
  children: ReactNode;
  needsRunFirst?: boolean;
}) {
  const ctx = useShellCtx();
  const st = ctx.detail.progress.stages[stage];
  const generated = !!st?.generated_at;
  const approved = !!st?.approved_at;
  const running = ctx.jobStatus?.status === "running";

  const [showReject, setShowReject] = useState(false);
  const [rejectFeedback, setRejectFeedback] = useState<string | null>(null);

  return (
    <div>
      <header className="flex justify-between items-start mb-6">
        <div>
          <h2 className="text-2xl font-bold">{title}</h2>
          {description && (
            <p className="text-slate-400 text-sm mt-1">{description}</p>
          )}
          <div className="mt-2 flex gap-2 text-xs">
            <span
              className={`badge ${
                generated
                  ? "bg-amber-700 text-amber-100"
                  : "bg-slate-700 text-slate-400"
              }`}
            >
              生成: {st?.generated_at ?? "未"}
            </span>
            <span
              className={`badge ${
                approved
                  ? "bg-emerald-700 text-emerald-100"
                  : "bg-slate-700 text-slate-400"
              }`}
            >
              承認: {st?.approved_at ?? "未"}
            </span>
            {st?.regen_count ? (
              <span className="badge bg-rose-700/40 text-rose-200">
                再生成 ×{st.regen_count}
              </span>
            ) : null}
            {rejectFeedback && (
              <span className="badge bg-rose-800/60 text-rose-100">
                {rejectFeedback}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          {generated && (
            <button
              className="btn-ghost text-rose-300 hover:text-rose-100"
              disabled={running}
              onClick={() => setShowReject(true)}
              title="QA failure として記録 (= 承認状態は変えません)"
            >
              ✗ NG 記録
            </button>
          )}
          {needsRunFirst && !generated && (
            <button
              className="btn-primary"
              disabled={running}
              onClick={() => ctx.runNext()}
            >
              このstageを生成
            </button>
          )}
          {generated && !approved && (
            <button
              className="btn-primary"
              disabled={running}
              onClick={() => ctx.approveCurrent(stage)}
            >
              ✓ OK 次のstageへ進む
            </button>
          )}
          {approved && (
            <span className="badge bg-emerald-700 text-emerald-100">
              承認済み
            </span>
          )}
        </div>
      </header>

      <div className={running ? "opacity-60 pointer-events-none" : ""}>
        {children}
      </div>

      {showReject && (
        <RejectModal
          ts={ctx.detail.timestamp}
          stage={stage}
          onClose={() => setShowReject(false)}
          onSubmitted={(id) => setRejectFeedback(`NG #${id} 記録済み`)}
        />
      )}
    </div>
  );
}
