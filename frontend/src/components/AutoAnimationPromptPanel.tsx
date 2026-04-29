import { useEffect, useState } from "react";
import { api } from "../api";

type AutoState = {
  manual: string | null;
  auto: string | null;
  structured: {
    subject: string;
    action_sequence: string;
    camera: string;
    mood: string;
  } | null;
  cached: boolean;
};

export default function AutoAnimationPromptPanel({
  ts,
  sceneIdx,
  onAdopted,
}: {
  ts: string;
  sceneIdx: number;
  onAdopted?: () => void;
}) {
  const [state, setState] = useState<AutoState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let canceled = false;
    api
      .getAutoAnimationPrompt(ts, sceneIdx)
      .then((r) => {
        if (!canceled) setState(r);
      })
      .catch(() => {});
    return () => {
      canceled = true;
    };
  }, [ts, sceneIdx]);

  const onGenerate = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.regenAutoAnimationPrompt(ts, sceneIdx);
      setState(r);
      setOpen(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const onAdopt = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.adoptAutoAnimationPrompt(ts, sceneIdx);
      setState({ ...state!, manual: r.manual, auto: r.auto });
      onAdopted?.();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const hasAuto = !!state?.auto;
  const isAdopted = state?.manual && state.auto && state.manual === state.auto;

  return (
    <div className="rounded border border-slate-700/60 bg-slate-900/40 px-2 py-2 mb-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold text-slate-300">
          AI 自動生成 (lines→Claude Sonnet)
        </div>
        <div className="flex gap-2">
          {hasAuto && (
            <button
              className="btn-ghost text-xs"
              onClick={() => setOpen((v) => !v)}
            >
              {open ? "閉じる" : "表示"}
            </button>
          )}
          <button
            className="btn-secondary text-xs"
            disabled={loading}
            onClick={onGenerate}
            title="セリフ・感情・delivery・acoustic から Claude Sonnet で animation_prompt を再生成"
          >
            {loading ? "生成中..." : hasAuto ? "再生成" : "自動生成"}
          </button>
          {hasAuto && !isAdopted && (
            <button
              className="btn-primary text-xs"
              disabled={loading}
              onClick={onAdopt}
              title="この prompt を animation_prompt に採用 (screenplay に保存)"
            >
              採用
            </button>
          )}
          {isAdopted && (
            <span className="text-emerald-400 text-xs self-center">
              採用済み
            </span>
          )}
        </div>
      </div>

      {error && <div className="text-rose-400 mt-1">{error}</div>}

      {open && hasAuto && (
        <div className="mt-2 space-y-1 text-slate-300">
          {state?.structured && (
            <div className="grid grid-cols-[80px_1fr] gap-x-2 gap-y-0.5">
              <span className="text-slate-500">subject</span>
              <span>{state.structured.subject}</span>
              <span className="text-slate-500">action</span>
              <span>{state.structured.action_sequence}</span>
              <span className="text-slate-500">camera</span>
              <span>{state.structured.camera}</span>
              <span className="text-slate-500">mood</span>
              <span>{state.structured.mood}</span>
            </div>
          )}
          <div className="border-t border-slate-700/40 pt-1">
            <span className="text-slate-500">composed:</span>
            <p className="font-mono text-[11px] mt-0.5 break-words">
              {state?.auto}
            </p>
          </div>
          {state?.manual && state.manual !== state.auto && (
            <div className="border-t border-slate-700/40 pt-1">
              <span className="text-slate-500">現在の手書き:</span>
              <p className="font-mono text-[11px] mt-0.5 break-words text-slate-400">
                {state.manual}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
