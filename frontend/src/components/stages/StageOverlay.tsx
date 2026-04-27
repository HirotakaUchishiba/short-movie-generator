import { useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { overlayAssetUrl, api } from "../../api";
import type { Screenplay, Line } from "../../types";

export default function StageOverlay() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const [draft, setDraft] = useState<Screenplay>(
    JSON.parse(JSON.stringify(sp)),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateLine = (sIdx: number, lIdx: number, patch: Partial<Line>) => {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d)) as Screenplay;
      const line = next.scenes[sIdx].lines![lIdx];
      next.scenes[sIdx].lines![lIdx] = { ...line, ...patch };
      return next;
    });
  };

  const onApply = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.saveScreenplay(ctx.detail.timestamp, draft);
      await ctx.reload();
      await ctx.regen({ stage: "overlay" });
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const sceneOffsets: number[] = [];
  let acc = 0;
  for (const s of sp.scenes) {
    sceneOffsets.push(acc);
    acc += s.duration;
  }

  return (
    <StageGate
      stage="overlay"
      title="Stage 7: 字幕オーバーレイ"
      description="Stage 5+6 のシーン動画を連結し、字幕 (lines[].text) を焼き込み。字幕の表示タイミング (start/end) のみ編集可。TTS音声は Stage 2 で確定済みなので変更されません。"
      needsRunFirst
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <div className="aspect-[9/16] bg-slate-950 overflow-hidden rounded mb-3 max-w-md mx-auto relative">
            <video
              key={ctx.detail.progress.stages.overlay.regen_count}
              src={overlayAssetUrl(
                ctx.detail.timestamp,
                ctx.detail.progress.stages.overlay.regen_count,
              )}
              controls
              playsInline
              className="w-full h-full"
            />
            <SubtitleYPositionGuide
              videoHeight={ctx.serverConfig.video_height}
              currentY={
                draft.subtitle_y_from_bottom ??
                ctx.serverConfig.subtitle_y_from_bottom
              }
            />
          </div>
          <SubtitleYPositionEditor
            current={
              draft.subtitle_y_from_bottom ??
              ctx.serverConfig.subtitle_y_from_bottom
            }
            videoHeight={ctx.serverConfig.video_height}
            isOverridden={draft.subtitle_y_from_bottom !== undefined}
            onChange={(value) =>
              setDraft((d) => ({ ...d, subtitle_y_from_bottom: value }))
            }
            onReset={() =>
              setDraft((d) => {
                const next = { ...d };
                delete next.subtitle_y_from_bottom;
                return next;
              })
            }
          />
        </div>
        <div className="card">
          <div className="flex justify-between items-center mb-3">
            <h3 className="font-semibold">字幕一覧</h3>
            <button className="btn-primary" disabled={saving} onClick={onApply}>
              {saving ? "焼き直し中..." : "保存して焼き直し"}
            </button>
          </div>
          <p className="text-[11px] text-slate-500 mb-2">
            字幕の表示タイミング (start/end) のみ編集可。テキストを変えるには
            Stage 1 (台本) または Stage 2 (TTS) へ。
          </p>
          {error && <div className="text-rose-400 text-xs mb-2">{error}</div>}
          <div className="max-h-[600px] overflow-auto">
            <table className="w-full text-xs">
              <thead className="text-slate-400 sticky top-0 bg-slate-800">
                <tr>
                  <th className="text-left p-1">S</th>
                  <th className="text-left p-1">絶対 開始</th>
                  <th className="text-left p-1">start</th>
                  <th className="text-left p-1">end</th>
                  <th className="text-left p-1">text</th>
                </tr>
              </thead>
              <tbody>
                {draft.scenes.flatMap((scene, sIdx) =>
                  (scene.lines ?? []).map((line, lIdx) => (
                    <tr
                      key={`${sIdx}-${lIdx}`}
                      className="border-t border-slate-700"
                    >
                      <td className="p-1 text-slate-500">{sIdx + 1}</td>
                      <td className="p-1 text-slate-500">
                        {(sceneOffsets[sIdx] + line.start).toFixed(2)}s
                      </td>
                      <td className="p-1">
                        <input
                          type="number"
                          step="0.1"
                          className="input text-xs py-1"
                          value={line.start}
                          onChange={(e) =>
                            updateLine(sIdx, lIdx, {
                              start: Number(e.target.value),
                            })
                          }
                        />
                      </td>
                      <td className="p-1">
                        <input
                          type="number"
                          step="0.1"
                          className="input text-xs py-1"
                          value={line.end ?? ""}
                          onChange={(e) =>
                            updateLine(sIdx, lIdx, {
                              end:
                                e.target.value === ""
                                  ? undefined
                                  : Number(e.target.value),
                            })
                          }
                        />
                      </td>
                      <td className="p-1 text-slate-300 break-words max-w-md">
                        {line.text}
                      </td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </StageGate>
  );
}

// 動画preview に重ねて表示する字幕Y位置のガイド帯。
// 現在の subtitle_y_from_bottom 値で「ここに字幕が入る」を視覚化する。
function SubtitleYPositionGuide({
  videoHeight,
  currentY,
}: {
  videoHeight: number;
  currentY: number;
}) {
  // 字幕の縦サイズはおおよそ画面高の 12% (固定)。中心が currentY に来るように描く。
  const heightPct = 12;
  const bottomPct = (currentY / videoHeight) * 100 - heightPct / 2;
  return (
    <div
      className="absolute left-0 right-0 pointer-events-none"
      style={{
        bottom: `${bottomPct}%`,
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
function SubtitleYPositionEditor({
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
        スライダー変更後「保存して焼き直し」を押すと反映 ( ffmpeg overlay
        のみ・無料)
      </p>
    </div>
  );
}
