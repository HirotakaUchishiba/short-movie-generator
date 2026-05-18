// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
// analyze pipeline が初期値として pre-fill した field の横に表示する小バッジ。

export function AnalyzeSuggestedBadge() {
  return (
    <span
      className="text-[10px] text-violet-300 bg-violet-500/10 rounded px-1.5 py-0.5"
      title="analyze が参考動画から推定した初期値です。必要なら修正してください"
    >
      ✨ analyze 推定
    </span>
  );
}
