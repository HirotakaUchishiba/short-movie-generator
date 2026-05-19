// StageOverlay.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 字幕Y位置 (画面下端からのピクセル数) を編集する 2 コンポ:
//   - SubtitleYPositionGuide: 動画 preview 領域に半透明のガイド帯を重ねる
//   - SubtitleYPositionEditor: スライダーで Y 位置を編集 + 既定リセット
//
// 両者は座標系を共有するため同 file に配置 (= 片方だけ import するのが
// 視覚的に妙な状態を引き起こすことは無い)。

// 動画preview に重ねて表示する字幕Y位置のガイド帯。
// 現在の subtitle_y_from_bottom 値で「ここに字幕が入る」を視覚化する。
export function SubtitleYPositionGuide({
  videoHeight,
  currentY,
  controlsPx = 40,
}: {
  videoHeight: number;
  currentY: number;
  // <Player controls> の bottom bar 高さ。実映像領域はコンテナ高 - controlsPx
  // となるため、`%` 基準の bottom にこの px を下駄として履かせないと、ガイドが
  // controls bar に被って常に「実字幕より下」にズレて見える。
  controlsPx?: number;
}) {
  // 字幕の縦サイズはおおよそ画面高の 12% (固定)。中心が currentY に来るように描く。
  const heightPct = 12;
  const bottomPct = (currentY / videoHeight) * 100 - heightPct / 2;
  return (
    <div
      className="absolute left-0 right-0 pointer-events-none"
      style={{
        bottom: `calc(${bottomPct}% + ${controlsPx}px)`,
        height: `${heightPct}%`,
        background: "rgba(56, 189, 248, 0.18)",
        borderTop: "1px dashed rgba(56, 189, 248, 0.6)",
        borderBottom: "1px dashed rgba(56, 189, 248, 0.6)",
      }}
      title={`字幕位置 (画面下端から ${currentY}px)`}
    />
  );
}

// 字幕Y位置を画面下端からのピクセル数で調整するスライダー。
export function SubtitleYPositionEditor({
  current,
  videoHeight,
  isOverridden,
  onChange,
  onReset,
}: {
  current: number;
  videoHeight: number;
  isOverridden: boolean;
  onChange: (value: number) => void;
  onReset: () => void;
}) {
  const max = videoHeight - 50;
  return (
    <div className="card border-sky-700/40 bg-sky-900/10 max-w-md mx-auto">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-sky-200">
          🎯 字幕Y位置 (画面下端からのピクセル)
        </h4>
        <button
          className="btn-ghost text-[10px] disabled:opacity-30"
          disabled={!isOverridden}
          onClick={onReset}
          title="既定値 (config.SUBTITLE_Y_FROM_BOTTOM) に戻す"
        >
          既定に戻す
        </button>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-slate-500 w-10 text-right">下端</span>
        <input
          type="range"
          min={50}
          max={max}
          step={10}
          value={current}
          onChange={(e) => onChange(Number(e.target.value))}
          className="flex-1 accent-sky-500"
        />
        <span className="text-[10px] text-slate-500 w-10">上端</span>
        <span className="font-mono text-xs text-slate-200 w-16 text-right">
          {current}px
        </span>
        <span
          className={
            "text-[10px] w-10 text-center " +
            (isOverridden ? "text-sky-300" : "text-slate-500")
          }
          title={isOverridden ? "個別値を設定中" : "config 既定値を使用中"}
        >
          {isOverridden ? "個別" : "既定"}
        </span>
      </div>
      <p className="text-[10px] text-slate-500 mt-1.5">
        スライダー変更は Player に即時反映。Stage 7 公開 mp4 を更新する場合は
        「🎬 最終 mp4 を焼き直す」を押す
      </p>
    </div>
  );
}
