import { Link } from "react-router-dom";
import type { Progress, StageName } from "../types";

const STAGES: { key: StageName; label: string }[] = [
  { key: "script", label: "1.台本" },
  { key: "tts", label: "2.TTS" },
  { key: "bg", label: "3.背景" },
  { key: "kling", label: "4.Kling" },
  { key: "scene", label: "5+6.シーン" },
  { key: "overlay", label: "7.字幕" },
  { key: "final", label: "完成" },
];

export default function StageProgressBar({
  progress,
  currentInPath,
  ts,
}: {
  progress: Progress;
  currentInPath: StageName;
  ts: string;
}) {
  return (
    <ol className="mt-3 flex flex-wrap gap-2 text-xs">
      {STAGES.map((s, i) => {
        const st = progress.stages[s.key];
        const generated = !!st?.generated_at;
        const approved = !!st?.approved_at;
        const isCurrent = s.key === currentInPath;
        let bg = "bg-slate-700 text-slate-400";
        if (approved) bg = "bg-emerald-700 text-emerald-100";
        else if (generated) bg = "bg-amber-700 text-amber-100";
        if (isCurrent) bg += " ring-2 ring-emerald-400";
        return (
          <li key={s.key}>
            <Link
              to={`/project/${ts}/${s.key}`}
              className={`badge ${bg} px-3 py-1 hover:opacity-80`}
            >
              {s.label}
              {st?.regen_count ? ` (再×${st.regen_count})` : ""}
            </Link>
            {i < STAGES.length - 1 && (
              <span className="mx-1 text-slate-500">→</span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
