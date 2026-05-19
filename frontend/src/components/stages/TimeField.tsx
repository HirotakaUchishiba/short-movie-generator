// StageOverlay.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 字幕チャンクの start/end 時刻を秒単位で入力する小型コンポ。
// 動画の現在再生位置を ⏱→start / ⏱→end ボタンで snap できる。

export function TimeField({
  label,
  value,
  onChange,
  onSnap,
}: {
  label: string;
  value: number | undefined;
  onChange: (v: number | undefined) => void;
  onSnap: () => void;
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-[10px] text-slate-500 w-8">{label}</span>
      <input
        type="number"
        step="0.05"
        className="input text-[11px] py-0.5 w-20"
        placeholder="auto"
        value={value ?? ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? undefined : Number(e.target.value))
        }
      />
      <button
        className="btn-ghost text-[10px]"
        onClick={onSnap}
        title={`動画の現在の再生位置を ${label} に反映 (シーン内相対秒)`}
      >
        ⏱→{label}
      </button>
    </div>
  );
}
