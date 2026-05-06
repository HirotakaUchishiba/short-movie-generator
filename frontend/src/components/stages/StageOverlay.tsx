import { useRef, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { overlayAssetUrl, api } from "../../api";
import type { Screenplay, Line, SubtitleChunk } from "../../types";

export default function StageOverlay() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const [draft, setDraft] = useState<Screenplay>(
    JSON.parse(JSON.stringify(sp)),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const sceneOffsets: number[] = [];
  let acc = 0;
  for (const s of sp.scenes) {
    sceneOffsets.push(acc);
    acc += s.duration;
  }

  // 動画 element の currentTime をシーン内相対秒に変換。
  // overlaid.mp4 の絶対時刻 - sceneOffsets[sIdx] を返す。
  const sceneRelNow = (sIdx: number): number | null => {
    const v = videoRef.current;
    if (!v) return null;
    const rel = v.currentTime - sceneOffsets[sIdx];
    if (rel < 0) return null;
    return Math.round(rel * 100) / 100;
  };

  const updateLine = (sIdx: number, lIdx: number, patch: Partial<Line>) => {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d)) as Screenplay;
      const line = next.scenes[sIdx].lines![lIdx];
      next.scenes[sIdx].lines![lIdx] = { ...line, ...patch };
      return next;
    });
  };

  const enableManual = (sIdx: number, lIdx: number) => {
    const line = draft.scenes[sIdx].lines![lIdx];
    // 初期: 1 chunk = line 全文 (時刻は未指定 = auto)
    const initial: SubtitleChunk[] = [{ text: line.text }];
    updateLine(sIdx, lIdx, { subtitles: initial });
    setExpanded((e) => ({ ...e, [`${sIdx}-${lIdx}`]: true }));
  };

  const disableManual = (sIdx: number, lIdx: number) => {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d)) as Screenplay;
      const line = next.scenes[sIdx].lines![lIdx];
      delete line.subtitles;
      return next;
    });
  };

  const writeChunk = (
    sIdx: number,
    lIdx: number,
    cIdx: number,
    mutator: (c: SubtitleChunk) => void,
  ) => {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d)) as Screenplay;
      const subs = next.scenes[sIdx].lines![lIdx].subtitles!;
      mutator(subs[cIdx]);
      return next;
    });
  };

  const setChunkText = (
    sIdx: number,
    lIdx: number,
    cIdx: number,
    text: string,
  ) =>
    writeChunk(sIdx, lIdx, cIdx, (c) => {
      c.text = text;
    });

  const setChunkTime = (
    sIdx: number,
    lIdx: number,
    cIdx: number,
    field: "start" | "end",
    value: number | undefined,
  ) =>
    writeChunk(sIdx, lIdx, cIdx, (c) => {
      if (value === undefined) delete c[field];
      else c[field] = value;
    });

  // 動画プレイヤーの currentTime をこのチャンクの start / end に反映。
  // 動画はシーン横断の絶対秒 → sceneOffsets[sIdx] を引いてシーン内相対秒に変換。
  const snapChunkTime = (
    sIdx: number,
    lIdx: number,
    cIdx: number,
    field: "start" | "end",
  ) => {
    const t = sceneRelNow(sIdx);
    if (t === null) return;
    setChunkTime(sIdx, lIdx, cIdx, field, t);
  };

  const clearChunkTime = (sIdx: number, lIdx: number, cIdx: number) =>
    writeChunk(sIdx, lIdx, cIdx, (c) => {
      delete c.start;
      delete c.end;
    });

  const splitChunk = (sIdx: number, lIdx: number, cIdx: number) => {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d)) as Screenplay;
      const subs = next.scenes[sIdx].lines![lIdx].subtitles!;
      const c = subs[cIdx];
      const midText = Math.max(1, Math.floor(c.text.length / 2));
      const left: SubtitleChunk = { text: c.text.slice(0, midText) };
      const right: SubtitleChunk = { text: c.text.slice(midText) };
      // 時刻が両方ある場合のみ中央分割で受け継ぐ。auto なら auto のまま。
      if (c.start !== undefined && c.end !== undefined) {
        const midTime = (c.start + c.end) / 2;
        left.start = c.start;
        left.end = midTime;
        right.start = midTime;
        right.end = c.end;
      }
      subs.splice(cIdx, 1, left, right);
      return next;
    });
  };

  const removeChunk = (sIdx: number, lIdx: number, cIdx: number) => {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d)) as Screenplay;
      const subs = next.scenes[sIdx].lines![lIdx].subtitles!;
      subs.splice(cIdx, 1);
      if (subs.length === 0) {
        delete next.scenes[sIdx].lines![lIdx].subtitles;
      }
      return next;
    });
  };

  const appendChunk = (sIdx: number, lIdx: number) => {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d)) as Screenplay;
      const line = next.scenes[sIdx].lines![lIdx];
      const subs = line.subtitles ?? [];
      subs.push({ text: "" });
      line.subtitles = subs;
      return next;
    });
  };

  const toggleLineHidden = (sIdx: number, lIdx: number) => {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d)) as Screenplay;
      const line = next.scenes[sIdx].lines![lIdx];
      if (line.hidden) {
        delete line.hidden;
      } else {
        line.hidden = true;
      }
      return next;
    });
  };

  const setSceneLinesHidden = (sIdx: number, hidden: boolean) => {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d)) as Screenplay;
      const lines = next.scenes[sIdx].lines ?? [];
      for (const line of lines) {
        if (hidden) line.hidden = true;
        else delete line.hidden;
      }
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

  return (
    <StageGate
      stage="overlay"
      title="字幕オーバーレイ"
      description="音声/リップシンク合成 のシーン動画を連結し、字幕を焼き込み。各 line を「手動」に切り替えると自動分割を完全にスキップ。チャンクは text だけ書けば line 範囲を文字数比例で自動配分し、動画の現在位置をスナップして個別微調整できます。👁 ボタンで line / シーン単位で字幕の表示/非表示を切替可 (TTS は通常通り)。"
      needsRunFirst
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <div className="aspect-[9/16] bg-slate-950 overflow-hidden rounded mb-3 max-w-md mx-auto relative">
            <video
              ref={videoRef}
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
          <p className="text-[11px] text-slate-500 mt-3 max-w-md mx-auto">
            動画を再生 → 一時停止して、各チャンクの「⏱→start」「⏱→end」ボタンで
            現在の再生位置をスナップ。空欄のチャンクは line
            全体を文字数比例で自動配分。
          </p>
        </div>
        <div className="card">
          <div className="flex justify-between items-center mb-3">
            <h3 className="font-semibold">
              字幕一覧 (line ごとに自動 / 手動切替)
            </h3>
            <button className="btn-primary" disabled={saving} onClick={onApply}>
              {saving ? "焼き直し中..." : "保存して焼き直し"}
            </button>
          </div>
          {error && <div className="text-rose-400 text-xs mb-2">{error}</div>}
          <div className="max-h-[640px] overflow-auto space-y-3">
            {draft.scenes.map((scene, sIdx) => {
              const lines = scene.lines ?? [];
              const allHidden =
                lines.length > 0 && lines.every((l) => l.hidden);
              const someHidden = lines.some((l) => l.hidden);
              return (
                <div key={sIdx} className="space-y-1.5">
                  <div className="flex items-center gap-2 px-1 py-1 border-b border-slate-700/60">
                    <span className="text-[11px] font-semibold text-slate-300">
                      Scene {sIdx + 1}
                    </span>
                    <span className="text-[10px] text-slate-600">
                      {sceneOffsets[sIdx].toFixed(1)}s〜
                    </span>
                    <div className="ml-auto flex items-center gap-1">
                      {someHidden && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-900/40 text-rose-300">
                          {allHidden ? "全hidden" : "一部hidden"}
                        </span>
                      )}
                      {lines.length > 0 && (
                        <button
                          className="btn-ghost text-[10px]"
                          onClick={() => setSceneLinesHidden(sIdx, !allHidden)}
                          title={
                            allHidden
                              ? "このシーンの字幕を全て表示に戻す"
                              : "このシーンの字幕を全て非表示にする"
                          }
                        >
                          {allHidden ? "全部表示" : "全部非表示"}
                        </button>
                      )}
                    </div>
                  </div>
                  {lines.map((line, lIdx) => {
                    const key = `${sIdx}-${lIdx}`;
                    const isManual = !!line.subtitles;
                    const isHidden = !!line.hidden;
                    const isExpanded = !isHidden && (isManual || expanded[key]);
                    return (
                      <div
                        key={key}
                        className={
                          "border border-slate-700 rounded p-2 bg-slate-900/40 " +
                          (isHidden ? "opacity-50" : "")
                        }
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-slate-500 w-10">
                            S{sIdx + 1}-L{lIdx + 1}
                          </span>
                          <span className="text-[10px] text-slate-500 w-16">
                            {(sceneOffsets[sIdx] + line.start).toFixed(2)}s〜
                          </span>
                          <span
                            className={
                              "text-xs flex-1 truncate " +
                              (isHidden
                                ? "text-slate-500 line-through"
                                : "text-slate-300")
                            }
                          >
                            {line.text}
                          </span>
                          <button
                            className={
                              "text-[14px] px-1 leading-none " +
                              (isHidden
                                ? "text-rose-400 hover:text-rose-300"
                                : "text-slate-400 hover:text-slate-200")
                            }
                            onClick={() => toggleLineHidden(sIdx, lIdx)}
                            title={
                              isHidden
                                ? "字幕を表示する"
                                : "この line の字幕を焼き込まない"
                            }
                          >
                            {isHidden ? "🚫" : "👁"}
                          </button>
                          {isManual ? (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-700/40 text-amber-200">
                              手動
                            </span>
                          ) : (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
                              自動
                            </span>
                          )}
                          {isManual ? (
                            <button
                              className="btn-ghost text-[10px]"
                              onClick={() => disableManual(sIdx, lIdx)}
                              title="手動チャンクを破棄して自動分割に戻す"
                              disabled={isHidden}
                            >
                              自動に戻す
                            </button>
                          ) : (
                            <button
                              className="btn-ghost text-[10px]"
                              onClick={() => enableManual(sIdx, lIdx)}
                              title="自動分割を無効化し、この line を手動チャンクで完全制御する"
                              disabled={isHidden}
                            >
                              手動に切替
                            </button>
                          )}
                          {!isManual && (
                            <button
                              className="btn-ghost text-[10px]"
                              onClick={() =>
                                setExpanded((e) => ({ ...e, [key]: !e[key] }))
                              }
                              disabled={isHidden}
                            >
                              {expanded[key] ? "閉じる" : "詳細"}
                            </button>
                          )}
                        </div>

                        {isExpanded && !isManual && (
                          <div className="mt-2 grid grid-cols-2 gap-2 pl-12">
                            <label className="text-[10px] text-slate-400">
                              start (相対秒)
                              <input
                                type="number"
                                step="0.1"
                                className="input text-xs py-1 mt-0.5"
                                value={line.start}
                                onChange={(e) =>
                                  updateLine(sIdx, lIdx, {
                                    start: Number(e.target.value),
                                  })
                                }
                              />
                            </label>
                            <label className="text-[10px] text-slate-400">
                              end (相対秒)
                              <input
                                type="number"
                                step="0.1"
                                className="input text-xs py-1 mt-0.5"
                                value={line.end ?? ""}
                                placeholder="(次line の start まで)"
                                onChange={(e) =>
                                  updateLine(sIdx, lIdx, {
                                    end:
                                      e.target.value === ""
                                        ? undefined
                                        : Number(e.target.value),
                                  })
                                }
                              />
                            </label>
                          </div>
                        )}

                        {isManual && !isHidden && (
                          <ManualChunksEditor
                            sIdx={sIdx}
                            chunks={line.subtitles!}
                            onChangeText={(cIdx, text) =>
                              setChunkText(sIdx, lIdx, cIdx, text)
                            }
                            onChangeTime={(cIdx, field, value) =>
                              setChunkTime(sIdx, lIdx, cIdx, field, value)
                            }
                            onSnap={(cIdx, field) =>
                              snapChunkTime(sIdx, lIdx, cIdx, field)
                            }
                            onClearTime={(cIdx) =>
                              clearChunkTime(sIdx, lIdx, cIdx)
                            }
                            onSplit={(cIdx) => splitChunk(sIdx, lIdx, cIdx)}
                            onRemove={(cIdx) => removeChunk(sIdx, lIdx, cIdx)}
                            onAppend={() => appendChunk(sIdx, lIdx)}
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </StageGate>
  );
}

function ManualChunksEditor({
  sIdx,
  chunks,
  onChangeText,
  onChangeTime,
  onSnap,
  onClearTime,
  onSplit,
  onRemove,
  onAppend,
}: {
  sIdx: number;
  chunks: SubtitleChunk[];
  onChangeText: (cIdx: number, text: string) => void;
  onChangeTime: (
    cIdx: number,
    field: "start" | "end",
    value: number | undefined,
  ) => void;
  onSnap: (cIdx: number, field: "start" | "end") => void;
  onClearTime: (cIdx: number) => void;
  onSplit: (cIdx: number) => void;
  onRemove: (cIdx: number) => void;
  onAppend: () => void;
}) {
  return (
    <div className="mt-2 ml-12 border-l-2 border-amber-700/40 pl-3">
      <div className="text-[10px] text-slate-500 mb-1">
        S{sIdx + 1} — 空欄の時刻は line 範囲を文字数比例で自動配分
      </div>
      {chunks.map((c, cIdx) => {
        const isAuto = c.start === undefined && c.end === undefined;
        return (
          <div
            key={cIdx}
            className="border-t border-slate-800 py-1.5 flex flex-col gap-1"
          >
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-500 w-4">{cIdx + 1}</span>
              <input
                type="text"
                className="input text-xs py-1 flex-1"
                value={c.text}
                placeholder="字幕テキスト"
                onChange={(e) => onChangeText(cIdx, e.target.value)}
              />
              <span
                className={
                  "text-[10px] px-1 rounded " +
                  (isAuto
                    ? "bg-slate-700 text-slate-400"
                    : "bg-amber-700/40 text-amber-200")
                }
              >
                {isAuto ? "auto" : "手打ち"}
              </span>
              <button
                className="btn-ghost text-[10px]"
                onClick={() => onSplit(cIdx)}
                title="このチャンクを文字数中央で 2 分割"
              >
                分割
              </button>
              <button
                className="btn-ghost text-[10px] text-rose-400"
                onClick={() => onRemove(cIdx)}
              >
                ×
              </button>
            </div>
            <div className="flex items-center gap-1.5 pl-6">
              <TimeField
                label="start"
                value={c.start}
                onChange={(v) => onChangeTime(cIdx, "start", v)}
                onSnap={() => onSnap(cIdx, "start")}
              />
              <TimeField
                label="end"
                value={c.end}
                onChange={(v) => onChangeTime(cIdx, "end", v)}
                onSnap={() => onSnap(cIdx, "end")}
              />
              {!isAuto && (
                <button
                  className="btn-ghost text-[10px]"
                  onClick={() => onClearTime(cIdx)}
                  title="時刻をクリアして auto (文字数比例配分) に戻す"
                >
                  auto に戻す
                </button>
              )}
            </div>
          </div>
        );
      })}
      <button
        className="btn-ghost text-[10px] mt-2"
        onClick={onAppend}
        title="末尾にチャンクを追加 (時刻は auto)"
      >
        + チャンク追加
      </button>
    </div>
  );
}

function TimeField({
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
