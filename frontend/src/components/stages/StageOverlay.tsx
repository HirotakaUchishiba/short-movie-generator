import { useEffect, useRef, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api } from "../../api";
import type { Screenplay, Line, SubtitleChunk } from "../../types";
import { freshUid } from "../../uid";
import {
  replaceChunk,
  replaceLine,
  replaceScene,
} from "../../utils/screenplayPath";
import { ManualChunksEditor } from "./ManualChunksEditor";
import { PrimaryPreviewPanel } from "./PrimaryPreviewPanel";
import { SubtitleYPositionEditor } from "./SubtitleYPositionEditor";

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
  // sp.scenes[].duration 累積で、compositor の字幕 offset (= merged の tpad 後
  // 位置 = duration 累積、_scene_offsets_merged) と一致するため、ここでのスナップ
  // 位置と最終動画の焼き込み位置が揃う。
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

// ManualChunksEditor は ./ManualChunksEditor.tsx に移管済 (= §3.1.3)。
// TimeField も ./TimeField.tsx に移管済。

// SubtitleYPositionGuide / SubtitleYPositionEditor は
// ./SubtitleYPositionEditor.tsx に移管済 (= §3.1.3)。

// PrimaryPreviewPanel は ./PrimaryPreviewPanel.tsx に移管済 (= §3.1.3)。
