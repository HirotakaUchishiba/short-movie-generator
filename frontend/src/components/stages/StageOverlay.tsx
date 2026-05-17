import { useEffect, useRef, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api, overlayAssetUrl } from "../../api";
import type { Screenplay, Line, SubtitleChunk } from "../../types";
import { freshUid } from "../../uid";
import {
  replaceChunk,
  replaceLine,
  replaceScene,
} from "../../utils/screenplayPath";

export default function StageOverlay() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const [draft, setDraft] = useState<Screenplay>(() => structuredClone(sp));
  // dirty flag: ローカル draft が server snapshot と乖離している間は ctx.reload()
  // で server 側 sp が更新されても上書きしない (= 編集中の作業を消さない)。
  // 保存成功時に false に戻し、その後 useEffect で server snapshot を取り込む。
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState<"save" | "render" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  // primary preview の <video> ref。snap 機能は currentTime (秒) を使って
  // 「現在再生位置を chunk start/end に反映」を維持する。
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // server snapshot が変わったら **未編集なら** local draft に取り込む。
  // ctx.reload() で sp は更新されるが旧コードは draft の lazy init で 1 回しか
  // 同期しなかったため、別 stage / 別 tab での編集が反映されず、保存時に
  // 古い draft で server 側を上書きする静かなデータロスト bug があった。
  useEffect(() => {
    if (!dirty) {
      setDraft(structuredClone(sp));
    }
    // dirty を deps に入れない: 編集開始 (= dirty true) で sync を停止し、
    // 保存成功で false に戻ると同時に直近の sp が反映される。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sp]);

  // setDraft の薄い wrapper。すべての mutation 経路から dirty を立てる。
  const editDraft = (mut: (d: Screenplay) => Screenplay) => {
    setDraft((d) => mut(d));
    setDirty(true);
  };

  const sceneOffsets: number[] = [];
  let acc = 0;
  for (const s of sp.scenes) {
    sceneOffsets.push(acc);
    acc += s.duration;
  }

  // <video> の現在再生位置 (= 秒) を scene 内相対秒として返す。sceneOffsets は
  // sp.scenes[].duration ベースなので、scene 実尺と sp.duration が乖離した
  // project では snap がわずかにずれる可能性がある (= 既存挙動と同等)。
  const sceneRelNow = (sIdx: number): number | null => {
    const v = videoRef.current;
    if (!v) return null;
    const rel = v.currentTime - sceneOffsets[sIdx];
    if (rel < 0) return null;
    return Math.round(rel * 100) / 100;
  };

  const updateLine = (sIdx: number, lIdx: number, patch: Partial<Line>) => {
    editDraft((d) => replaceLine(d, sIdx, lIdx, (l) => ({ ...l, ...patch })));
  };

  const enableManual = (sIdx: number, lIdx: number) => {
    const line = draft.scenes[sIdx].lines![lIdx];
    // 初期: 1 chunk = line 全文 (時刻は未指定 = auto)
    const initial: SubtitleChunk[] = [{ text: line.text, _uid: freshUid() }];
    updateLine(sIdx, lIdx, { subtitles: initial });
    const k = line._uid ?? `${sIdx}-${lIdx}`;
    setExpanded((e) => ({ ...e, [k]: true }));
  };

  const disableManual = (sIdx: number, lIdx: number) => {
    editDraft((d) =>
      replaceLine(d, sIdx, lIdx, (l) => {
        const { subtitles: _drop, ...rest } = l;
        return rest as Line;
      }),
    );
  };

  const writeChunk = (
    sIdx: number,
    lIdx: number,
    cIdx: number,
    mutator: (c: SubtitleChunk) => SubtitleChunk,
  ) => {
    editDraft((d) => replaceChunk(d, sIdx, lIdx, cIdx, mutator));
  };

  const setChunkText = (
    sIdx: number,
    lIdx: number,
    cIdx: number,
    text: string,
  ) => writeChunk(sIdx, lIdx, cIdx, (c) => ({ ...c, text }));

  const setChunkTime = (
    sIdx: number,
    lIdx: number,
    cIdx: number,
    field: "start" | "end",
    value: number | undefined,
  ) =>
    writeChunk(sIdx, lIdx, cIdx, (c) => {
      const next = { ...c };
      if (value === undefined) delete next[field];
      else next[field] = value;
      return next;
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
      const next = { ...c };
      delete next.start;
      delete next.end;
      return next;
    });

  const splitChunk = (sIdx: number, lIdx: number, cIdx: number) => {
    editDraft((d) =>
      replaceLine(d, sIdx, lIdx, (line) => {
        const subs = (line.subtitles ?? []).slice();
        const c = subs[cIdx];
        const midText = Math.max(1, Math.floor(c.text.length / 2));
        const left: SubtitleChunk = {
          text: c.text.slice(0, midText),
          _uid: freshUid(),
        };
        const right: SubtitleChunk = {
          text: c.text.slice(midText),
          _uid: freshUid(),
        };
        // 時刻が両方ある場合のみ中央分割で受け継ぐ。auto なら auto のまま。
        if (c.start !== undefined && c.end !== undefined) {
          const midTime = (c.start + c.end) / 2;
          left.start = c.start;
          left.end = midTime;
          right.start = midTime;
          right.end = c.end;
        }
        subs.splice(cIdx, 1, left, right);
        return { ...line, subtitles: subs };
      }),
    );
  };

  const removeChunk = (sIdx: number, lIdx: number, cIdx: number) => {
    editDraft((d) =>
      replaceLine(d, sIdx, lIdx, (line) => {
        const subs = (line.subtitles ?? []).slice();
        subs.splice(cIdx, 1);
        if (subs.length === 0) {
          const { subtitles: _drop, ...rest } = line;
          return rest as Line;
        }
        return { ...line, subtitles: subs };
      }),
    );
  };

  const appendChunk = (sIdx: number, lIdx: number) => {
    editDraft((d) =>
      replaceLine(d, sIdx, lIdx, (line) => {
        const subs = (line.subtitles ?? []).slice();
        subs.push({ text: "", _uid: freshUid() });
        return { ...line, subtitles: subs };
      }),
    );
  };

  const toggleLineHidden = (sIdx: number, lIdx: number) => {
    editDraft((d) =>
      replaceLine(d, sIdx, lIdx, (line) => {
        if (line.hidden) {
          const { hidden: _drop, ...rest } = line;
          return rest as Line;
        }
        return { ...line, hidden: true };
      }),
    );
  };

  const setSceneLinesHidden = (sIdx: number, hidden: boolean) => {
    editDraft((d) =>
      replaceScene(d, sIdx, (scene) => {
        const lines = (scene.lines ?? []).map((line) => {
          if (hidden) return { ...line, hidden: true };
          if (!line.hidden) return line;
          const { hidden: _drop, ...rest } = line;
          return rest as Line;
        });
        return { ...scene, lines };
      }),
    );
  };

  // 「保存」と「最終 mp4 を焼き直す (= 公開準備)」を分離する。
  // - onSave:    screenplay を PUT するだけ。AI 課金 0 / レンダリングなし
  // - onRender:  保存 + ffmpeg で最終 mp4 を生成。Stage 7 公開前に必要
  const onSave = async () => {
    setPending("save");
    setError(null);
    try {
      await api.saveScreenplay(ctx.detail.timestamp, draft);
      // 保存成功で dirty を落とす → useEffect が server snapshot で sync する
      setDirty(false);
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(null);
    }
  };

  const onRender = async () => {
    setPending("render");
    setError(null);
    try {
      await api.saveScreenplay(ctx.detail.timestamp, draft);
      setDirty(false);
      await ctx.reload();
      await ctx.regen({ stage: "overlay" });
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(null);
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
          {/* ffmpeg-baked overlaid.mp4 を <video> で再生する primary preview。
              再焼き直し後は bumpKey が更新され、cache を避けて最新 mp4 を表示する。
              videoRef.currentTime で snap 機能 (= chunk start/end への反映) を提供。 */}
          <PrimaryPreviewPanel
            ts={ctx.detail.timestamp}
            bumpKey={ctx.detail.progress.stages.overlay.regen_count}
            videoRef={videoRef}
            videoHeight={ctx.serverConfig.video_height}
            currentSubtitleY={
              draft.subtitle_y_from_bottom ??
              ctx.serverConfig.subtitle_y_from_bottom
            }
          />
          <SubtitleYPositionEditor
            current={
              draft.subtitle_y_from_bottom ??
              ctx.serverConfig.subtitle_y_from_bottom
            }
            videoHeight={ctx.serverConfig.video_height}
            isOverridden={draft.subtitle_y_from_bottom !== undefined}
            onChange={(value) =>
              editDraft((d) => ({ ...d, subtitle_y_from_bottom: value }))
            }
            onReset={() =>
              editDraft((d) => {
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
          <div className="flex justify-between items-center mb-3 gap-2 flex-wrap">
            <h3 className="font-semibold">
              字幕一覧 (line ごとに自動 / 手動切替)
            </h3>
            <div className="flex items-center gap-2">
              <button
                className="btn-ghost text-xs"
                disabled={pending !== null}
                onClick={onSave}
                title="screenplay JSON を保存。Player の preview は即座に再 fetch される。最終 mp4 は焼き直さない (= AI 課金 0 / 数秒)"
              >
                {pending === "save" ? "保存中..." : "💾 保存"}
              </button>
              <button
                className="btn-primary text-xs"
                disabled={pending !== null}
                onClick={onRender}
                title="保存 + 最終 mp4 を再 render (= ffmpeg)。Stage 7 公開前に実行する"
              >
                {pending === "render"
                  ? "焼き直し中..."
                  : "🎬 最終 mp4 を焼き直す"}
              </button>
            </div>
          </div>
          <p className="text-[10px] text-slate-500 mb-2">
            💾 保存だけなら字幕 chunk 編集はサーバに反映される (=
            焼き直し不要)。 🎬 焼き直しは Stage 7 公開 mp4
            を更新する時のみ必要。
          </p>
          {error && <div className="text-rose-400 text-xs mb-2">{error}</div>}
          <div className="max-h-[640px] overflow-auto space-y-3">
            {draft.scenes.map((scene, sIdx) => {
              const lines = scene.lines ?? [];
              const allHidden =
                lines.length > 0 && lines.every((l) => l.hidden);
              const someHidden = lines.some((l) => l.hidden);
              return (
                <div key={scene._uid ?? sIdx} className="space-y-1.5">
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
                    // _uid を expanded state の key に。index 起点だと line を
                    // 並び替えると別 line に expanded フラグが貼り付く (= React
                    // 公式 anti-pattern)。`_uid` は freshUid() で line ごとに
                    // unique 採番される。
                    const key = line._uid ?? `${sIdx}-${lIdx}`;
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
            key={c._uid ?? cIdx}
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
        スライダー変更は Player に即時反映。Stage 7 公開 mp4 を更新する場合は
        「🎬 最終 mp4 を焼き直す」を押す
      </p>
    </div>
  );
}

// ffmpeg-baked overlaid.mp4 を <video> で再生する primary preview。videoRef を
// 親 (StageOverlay) で保持し、currentTime ベースで chunk snap に使う。
// SubtitleYPositionGuide は video 領域上に重ねて Y 位置編集の視覚的
// フィードバックを提供する。
function PrimaryPreviewPanel({
  ts,
  bumpKey,
  videoRef,
  videoHeight,
  currentSubtitleY,
}: {
  ts: string;
  bumpKey: number;
  videoRef: React.MutableRefObject<HTMLVideoElement | null>;
  videoHeight: number;
  currentSubtitleY: number;
}) {
  // bumpKey が変わった時 (= 再焼き直し直後) に強制再ロードして cache を回避する。
  const src = overlayAssetUrl(ts, bumpKey);
  return (
    <div className="max-w-md mx-auto mb-3">
      <div className="aspect-[9/16] bg-slate-950 overflow-hidden rounded relative">
        <video
          ref={videoRef}
          key={bumpKey}
          src={src}
          controls
          loop
          className="w-full h-full object-contain"
        />
        <SubtitleYPositionGuide
          videoHeight={videoHeight}
          currentY={currentSubtitleY}
        />
      </div>
    </div>
  );
}
