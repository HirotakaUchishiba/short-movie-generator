import { useEffect, useMemo, useState } from "react";
import { useShellCtx } from "../StageGate";
import { api, characterAssetUrl, referenceVideoAssetUrl } from "../../api";
import type {
  AbstractDiagnostics,
  AbstractScreenplay,
  AnalyzeJobDetail,
} from "../../types";
import { freshUid } from "../../uid";
import {
  ScriptEditContext,
  type ScriptEditContextValue,
} from "./ScriptEditContext";
import {
  CAMERA_DISTANCE_OPTIONS,
  collectAllLineSpeakers,
  collectRawSpeakerResidue,
  computeDiagnostics,
  fmtCost,
  groupByBase,
  joinRef,
  resolveLineSpeaker,
  splitRef,
  wardrobeLabel,
} from "./script-edit-utils";
import { AnalyzeSuggestedBadge } from "./AnalyzeSuggestedBadge";
import { BaseCharacterCard } from "./BaseCharacterCard";
import { BulkApplyBar } from "./BulkApplyBar";
import { CameraDistancePicker } from "./CameraDistancePicker";
import { CompletenessBanner } from "./CompletenessBanner";
import { LocationPicker } from "./LocationPicker";
import { ScriptEditRow } from "./ScriptEditRow";

// resolveLineSpeaker / collectRawSpeakerResidue / computeDiagnostics は
// 外部テスト / import で参照されるため re-export を保つ (§3.1.3-c)。
export { collectRawSpeakerResidue, computeDiagnostics, resolveLineSpeaker };

const EMOTIONS = [
  "驚き",
  "喜び",
  "焦り",
  "落胆",
  "中立",
  "満足",
  "困惑",
  "怒り",
  "恥ずかしさ",
];

type Status = "idle" | "loading" | "saving" | "ok" | "error";

/**
 * Stage 1 ページの編集セクション。analyze_job_id を持つプロジェクト
 * でのみ表示される。caption / featured_characters / speaker_to_ref /
 * 各シーンの animation_style / character_selection / lines
 * (text・emotion・speaker) を編集し、snapshot を abstract のまま PUT する
 * (= live derivation で Stage 2 以降が都度 compose を走らせる)。
 * location_ref / camera_distance は analyze が SSOT として自動産出するため
 * 編集 UI を持たない。
 */
export default function ScriptEditPanel({
  ts,
  jobId,
}: {
  ts: string;
  jobId: string;
}) {
  const ctx = useShellCtx();
  const [job, setJob] = useState<AnalyzeJobDetail | null>(null);
  const [abstract, setAbstract] = useState<AbstractScreenplay | null>(null);
  const [characterRefs, setCharacterRefs] = useState<string[]>([]);
  // locations/<id>.json の id 一覧 (= LocationPicker の選択肢)。analyze が
  // pre-fill した scene.location_ref をユーザが訂正できるようにするために fetch。
  const [locationIds, setLocationIds] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [boundaryWorking, setBoundaryWorking] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .listLocations()
      .then((d) => {
        if (!cancelled) setLocationIds(d.locations.map((l) => l.id));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.getAnalyzeJob(jobId),
      api.getProjectAbstract(ts),
      api.listCharacters(),
    ])
      .then(([j, ab, chars]) => {
        if (cancelled) return;
        setJob(j);
        setAbstract(ab.abstract);
        setCharacterRefs(chars.characters);
        setStatus("idle");
      })
      .catch((e) => {
        if (cancelled) return;
        setMessage(String(e));
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, ts]);

  const sceneCount = abstract?.scenes.length ?? 0;
  const lineCount = useMemo(
    () =>
      abstract?.scenes.reduce((acc, s) => acc + (s.lines?.length ?? 0), 0) ?? 0,
    [abstract],
  );

  // 各シーンの先頭セリフが flat 順で何番目かを累積で求める。
  // SceneEditor に渡して #N の絶対 index を出すのと、▲▼ 移動後の境界算出に使う。
  const flatStartByScene = useMemo(() => {
    const out: number[] = [];
    let cum = 0;
    for (const s of abstract?.scenes ?? []) {
      out.push(cum);
      cum += s.lines?.length ?? 0;
    }
    return out;
  }, [abstract]);

  // 編集と同期する completeness diagnostics。abstract / characterRefs が変わる
  // たびに再計算され、保存ボタンを押さなくてもバナーが即座に更新される。
  const liveDiagnostics = useMemo<AbstractDiagnostics | null>(() => {
    if (!abstract) return null;
    return computeDiagnostics(abstract, characterRefs);
  }, [abstract, characterRefs]);

  // Stage 2 (TTS) 完了後にだけシーン境界変更を許可する。
  // tts_full.mp3 が無いと apply_scene_boundaries は audio 再分割をスキップし
  // 中途半端な状態になるため、UI 側で disable する。
  const ttsReady = ctx.detail.progress.stages.tts.generated_at != null;

  // 成功メッセージは 4 秒で自動消去 (= エラーは残して原因確認させる)。
  useEffect(() => {
    if (status !== "ok" || !message) return;
    const t = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(t);
  }, [message, status]);

  const onSaveAbstract = async () => {
    if (!abstract) return;
    setStatus("saving");
    setMessage(null);
    try {
      await api.putProjectAbstract(ts, abstract);
      setDirty(false);
      setStatus("ok");
      setMessage(
        "保存しました (各ステージの承認は解除されました、assets は保持)",
      );
      // diagnostics は frontend で abstract から再計算されるので取り直し不要
      await ctx.reload();
    } catch (e) {
      setStatus("error");
      setMessage(String(e));
    }
  };

  // 全シーンに同じ値を一括適用する。animation_style のみ対応
  // (= location_ref / camera_distance は analyze が SSOT)。
  type BulkField = "animation_style";
  const applyToAllScenes = (field: BulkField, value: string | undefined) => {
    if (!abstract) return;
    const scenes = abstract.scenes.map((s) => {
      const next = { ...s };
      if (value === undefined || value === "") {
        delete (next as Record<string, unknown>)[field];
      } else {
        (next as Record<string, unknown>)[field] = value;
      }
      return next;
    });
    setAbstract({ ...abstract, scenes });
    setDirty(true);
  };

  const addScene = (afterIdx?: number) => {
    if (!abstract) return;
    // 空 text の line は schema (text.minLength=1) で reject されるため、
    // 新規シーンは lines:[] で開始し、ユーザーが「+ セリフ追加」してから
    // text を埋めて保存する流れにする。duration も Stage 2 が書き込む。
    const newScene: AbstractScreenplay["scenes"][number] = {
      lines: [],
      _uid: freshUid(),
    };
    const scenes = [...abstract.scenes];
    const insertAt =
      afterIdx === undefined ? scenes.length : Math.max(0, afterIdx + 1);
    scenes.splice(insertAt, 0, newScene);
    setAbstract({ ...abstract, scenes });
    setDirty(true);
  };

  const deleteScene = (sceneIdx: number) => {
    if (!abstract) return;
    if (abstract.scenes.length <= 1) {
      setStatus("error");
      setMessage("最後のシーンは削除できません (最低 1 シーン必要)");
      return;
    }
    if (!window.confirm(`シーン #${sceneIdx + 1} を削除しますか?`)) return;
    const scenes = abstract.scenes.filter((_, i) => i !== sceneIdx);
    setAbstract({ ...abstract, scenes });
    setDirty(true);
  };

  // line を隣接シーンへ移動 (= scene 境界の変更)。
  // テキスト・順序は不変なので applySceneBoundaries で済む = ElevenLabs 再課金なし。
  const moveLineToScene = async (
    flatIdx: number,
    fromScene: number,
    toScene: number,
  ) => {
    if (!abstract) return;
    if (toScene === fromScene) return;
    if (Math.abs(fromScene - toScene) !== 1) {
      setStatus("error");
      setMessage("順序を保つため、隣接するシーンにのみ移動できます");
      return;
    }
    if (!ttsReady) {
      setStatus("error");
      setMessage(
        "TTS 完了後にシーン境界を変更できます。先に TTS を実行してください",
      );
      return;
    }
    // dirty なら境界変更前に自動保存 (= 旧版の手動保存ステップを内蔵化)
    if (dirty) {
      try {
        await api.putProjectAbstract(ts, abstract);
        setDirty(false);
      } catch (e) {
        setStatus("error");
        setMessage(`自動保存に失敗: ${String(e)}`);
        return;
      }
    }
    const currentBoundaries = flatStartByScene.slice();
    const totalLines = lineCount;
    const next = new Set(currentBoundaries);
    if (toScene === fromScene - 1) {
      // 前のシーンへ移動: 今のシーンの開始境界を後ろにずらす
      const oldB = currentBoundaries[fromScene];
      next.delete(oldB);
      const newB = flatIdx + 1;
      if (newB < totalLines) next.add(newB);
    } else {
      // 次のシーンへ移動: 次のシーンの開始境界を前にずらす
      const oldB = currentBoundaries[fromScene + 1];
      if (oldB !== undefined) next.delete(oldB);
      if (flatIdx > currentBoundaries[fromScene]) {
        next.add(flatIdx);
      }
    }
    const newBoundaries = Array.from(next).sort((a, b) => a - b);
    if (
      JSON.stringify(newBoundaries) ===
      JSON.stringify(currentBoundaries.slice().sort((a, b) => a - b))
    ) {
      return;
    }
    setBoundaryWorking(true);
    setMessage(null);
    try {
      const r = await api.applySceneBoundaries(ts, newBoundaries);
      // snapshot が更新されたので abstract も再フェッチ
      const ab = await api.getProjectAbstract(ts);
      setAbstract(ab.abstract);
      setStatus("ok");
      setMessage(
        `シーン境界を更新しました (${r.scenes} シーン / ${r.lines} セリフ)`,
      );
      await ctx.reload();
    } catch (e) {
      setStatus("error");
      setMessage(String(e));
    } finally {
      setBoundaryWorking(false);
    }
  };

  if (status === "loading") {
    return (
      <div className="card text-sm text-slate-400">
        編集セクションを読み込み中…
      </div>
    );
  }
  if (!abstract || !job) {
    return (
      <div className="card border border-rose-500/40 text-sm text-rose-200">
        編集セクションの読み込みに失敗: {message ?? "unknown"}
      </div>
    );
  }

  const contextValue: ScriptEditContextValue = {
    ts,
    jobId,
    job,
    abstract,
    setAbstract,
    diagnostics: liveDiagnostics,
    characterRefs,
    locationIds,
    dirty,
    setDirty,
  };

  return (
    <ScriptEditContext.Provider value={contextValue}>
      <div className="space-y-4">
        {message && (
          <div
            className={`rounded p-2 text-xs whitespace-pre-wrap ${
              status === "error"
                ? "bg-rose-900/30 text-rose-200 border border-rose-500/40"
                : "bg-emerald-900/30 text-emerald-200 border border-emerald-500/40"
            }`}
          >
            {message}
          </div>
        )}

        {/* completeness バナー (compose 不整合があれば赤、無ければ緑) */}
        {liveDiagnostics && (
          <CompletenessBanner
            diag={liveDiagnostics}
            captionEmpty={!abstract.caption.trim()}
            featuredEmpty={
              !Array.isArray(abstract.featured_characters) ||
              abstract.featured_characters.length === 0
            }
          />
        )}

        {/* ① 台本作成 (caption + シーン境界 + lines + シーン override) */}
        <div className="card space-y-3">
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold">📝 台本作成</h3>
            <span className="text-xs text-slate-500">
              {sceneCount} シーン · {lineCount} セリフ
            </span>
          </div>

          {/* 全シーン一括適用 (= 17 シーンクリック地獄の解消) */}
          <BulkApplyBar onApply={applyToAllScenes} />

          <label className="block">
            <span className="text-xs text-slate-400">caption (SNS 投稿文)</span>
            <textarea
              className="input font-mono mt-1 text-base leading-relaxed"
              rows={6}
              value={abstract.caption}
              onChange={(e) => {
                setAbstract({ ...abstract, caption: e.target.value });
                setDirty(true);
              }}
            />
          </label>

          {/* 👥 動画全体の登場人物 (caption 直下) */}
          <FeaturedCharactersSection
            allRefs={characterRefs}
            selected={
              Array.isArray(abstract.featured_characters)
                ? abstract.featured_characters
                : []
            }
            isExplicit={Array.isArray(abstract.featured_characters)}
            analyzeSuggested={false}
            onChange={(next) => {
              setAbstract({ ...abstract, featured_characters: next });
              setDirty(true);
            }}
            onClearExplicit={() => {
              const copy = { ...abstract };
              delete copy.featured_characters;
              setAbstract(copy);
              setDirty(true);
            }}
          />

          <p className="text-[11px] text-slate-500 leading-relaxed">
            ※ 各シーンの先頭セリフの <strong>▲</strong> / 末尾セリフの{" "}
            <strong>▼</strong> を押すと隣のシーンへ移動できます (順序保持のため
            ±1 シーンのみ)。 テキスト・順序は不変なので ElevenLabs
            の追加課金は発生しません。
            {boundaryWorking && (
              <span className="ml-2 text-amber-400">境界更新中…</span>
            )}
          </p>

          <div className="space-y-5">
            {abstract.scenes.map((scene, sIdx) => (
              <SceneEditor
                key={scene._uid ?? sIdx}
                sIdx={sIdx}
                scene={scene}
                featuredRefs={
                  Array.isArray(abstract.featured_characters)
                    ? abstract.featured_characters
                    : []
                }
                allScenes={abstract.scenes}
                locationIds={locationIds}
                analyzeSuggested={false}
                flatStartIdx={flatStartByScene[sIdx] ?? 0}
                sceneCount={sceneCount}
                boundaryWorking={boundaryWorking}
                ttsReady={ttsReady}
                onSceneChange={(updater) => {
                  // immutable update: scenes 配列も新規作成して元の参照を破壊しない
                  const nextScenes = [...abstract.scenes];
                  nextScenes[sIdx] = updater(nextScenes[sIdx]);
                  setAbstract({ ...abstract, scenes: nextScenes });
                  setDirty(true);
                }}
                onSceneSpeakerBulkApply={(oldRef, newRef) => {
                  // 全 scene の line.speaker が oldRef なら newRef に置換
                  // (= 旧 speaker_to_ref bulk edit の代替)
                  const nextScenes = abstract.scenes.map((sc) => ({
                    ...sc,
                    lines: (sc.lines ?? []).map((ln) =>
                      ln.speaker === oldRef ? { ...ln, speaker: newRef } : ln,
                    ),
                  }));
                  setAbstract({ ...abstract, scenes: nextScenes });
                  setDirty(true);
                }}
                onMoveLine={(flatIdx, fromScene, toScene) => {
                  void moveLineToScene(flatIdx, fromScene, toScene);
                }}
                onAddSceneAfter={() => addScene(sIdx)}
                onDeleteScene={() => deleteScene(sIdx)}
              />
            ))}
          </div>

          {/* 末尾にシーン追加 */}
          <button
            className="btn-ghost text-xs"
            onClick={() => addScene()}
            title="末尾に新規シーンを追加"
          >
            + シーンを末尾に追加
          </button>

          <div className="flex items-center gap-3 pt-1 border-t border-slate-700">
            <button
              className="btn-secondary"
              disabled={
                !dirty || status === "saving" || !abstract.caption.trim()
              }
              onClick={onSaveAbstract}
              title={
                !abstract.caption.trim()
                  ? "caption が空のままでは保存できません"
                  : undefined
              }
            >
              {status === "saving" ? "保存中…" : "💾 台本作成を保存"}
            </button>
            {dirty && (
              <span className="text-xs text-amber-400">
                未保存の編集があります
              </span>
            )}
            <span className="text-xs text-slate-500 ml-auto">
              ※ caption / lines の編集はここで保存。シーン override は再合成時に
              反映 (保存不要)。
            </span>
          </div>
        </div>

        {/* ② 参考動画 (default 閉) */}
        <details className="card">
          <summary className="cursor-pointer text-sm text-slate-400 select-none">
            📹 参考動画 + analyze ジョブ情報
          </summary>
          <div className="mt-3 flex flex-wrap gap-4 items-start">
            <video
              src={referenceVideoAssetUrl(job.video_sha256)}
              controls
              className="w-64 max-w-full bg-black rounded"
            />
            <dl className="text-xs text-slate-400 space-y-1">
              <ScriptEditRow label="job id" value={job.id} mono />
              <ScriptEditRow label="status" value={job.status} />
              <ScriptEditRow
                label="video sha256"
                value={`${job.video_sha256.slice(0, 16)}…`}
                mono
              />
              <ScriptEditRow
                label="cost (実)"
                value={fmtCost(job.actual_cost_usd)}
              />
              <ScriptEditRow
                label="finished at"
                value={job.finished_at ?? "—"}
              />
            </dl>
          </div>
        </details>
      </div>
    </ScriptEditContext.Provider>
  );
}

function SceneEditor({
  sIdx,
  scene,
  featuredRefs,
  allScenes,
  locationIds,
  analyzeSuggested,
  flatStartIdx,
  sceneCount,
  boundaryWorking,
  ttsReady,
  onSceneChange,
  onSceneSpeakerBulkApply,
  onMoveLine,
  onAddSceneAfter,
  onDeleteScene,
}: {
  sIdx: number;
  scene: AbstractScreenplay["scenes"][number];
  featuredRefs: string[];
  /** project の全 scene (= SpeakerPicker の implicit active + bulk-apply 用) */
  allScenes: AbstractScreenplay["scenes"];
  /** LocationPicker の選択肢 (= locations/<id>.json の id 一覧) */
  locationIds: string[];
  /** analyze が casting 検出を実行したか (= 「✨ analyze 推定」バッジ表示) */
  analyzeSuggested: boolean;
  flatStartIdx: number;
  sceneCount: number;
  boundaryWorking: boolean;
  ttsReady: boolean;
  onSceneChange: (
    fn: (
      s: AbstractScreenplay["scenes"][number],
    ) => AbstractScreenplay["scenes"][number],
  ) => void;
  /** 全 scene の line.speaker oldRef を newRef に一括置換する */
  onSceneSpeakerBulkApply: (oldRef: string, newRef: string) => void;
  onMoveLine: (flatIdx: number, fromScene: number, toScene: number) => void;
  onAddSceneAfter: () => void;
  onDeleteScene: () => void;
}) {
  return (
    <div className="rounded-lg border-2 border-slate-600 bg-slate-900/40 shadow-md shadow-black/20 overflow-hidden">
      <div className="flex items-center gap-3 flex-wrap text-xs bg-slate-700/40 px-3 py-2 border-b-2 border-slate-600">
        <span className="font-mono text-sm text-emerald-300 font-semibold">
          シーン #{sIdx + 1}
        </span>
        <span className="text-slate-400">
          {scene.lines?.length ?? 0} セリフ
        </span>
        <span className="text-[11px] text-slate-500">
          duration は TTS の実音声長から自動算出
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            className="text-xs text-slate-400 hover:text-emerald-300 hover:bg-slate-700/60 rounded px-2 py-0.5"
            onClick={onAddSceneAfter}
            title="このシーンの直後に新しいシーンを追加"
          >
            + 下に追加
          </button>
          <button
            type="button"
            className="text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-900/20 rounded px-2 py-0.5"
            onClick={onDeleteScene}
            title="このシーンを削除"
          >
            × 削除
          </button>
        </div>
      </div>

      <div className="p-3 space-y-3">
        {/* シーン個別設定 (= 背景 / カメラ距離 / 動き)。analyze が pre-fill
            した値を初期表示し、ユーザが訂正できる。 */}
        <div className="space-y-2 text-xs">
          <div className="bg-slate-800/40 rounded p-2 space-y-2">
            {analyzeSuggested && (
              <div className="flex justify-end">
                <AnalyzeSuggestedBadge />
              </div>
            )}
            <LocationPicker
              scene={scene}
              locationIds={locationIds}
              onSceneChange={onSceneChange}
            />
            <CameraDistancePicker scene={scene} onSceneChange={onSceneChange} />
            <label className="flex items-center gap-1">
              <span className="text-slate-500 shrink-0">🎬 動き</span>
              <select
                className="select text-xs flex-1"
                value={scene.animation_style ?? ""}
                onChange={(e) => {
                  const v = e.target.value;
                  onSceneChange((s) => {
                    const next = { ...s };
                    if (v) {
                      next.animation_style = v as NonNullable<
                        typeof next.animation_style
                      >;
                    } else {
                      delete next.animation_style;
                    }
                    return next;
                  });
                }}
              >
                <option value="">(既定: standard)</option>
                <option value="subtle">subtle (控えめ)</option>
                <option value="standard">standard (標準)</option>
                <option value="expressive">expressive (派手)</option>
              </select>
            </label>
          </div>
        </div>

        {/* 登場人物セレクタ (背景生成時にどのキャラを写すか) */}
        {featuredRefs.length > 0 && (
          <SceneCharacterSelector
            characters={featuredRefs}
            selection={scene.character_selection}
            onChange={(sel) =>
              onSceneChange((s) => {
                const next = { ...s };
                if (sel === null) {
                  delete (next as Record<string, unknown>).character_selection;
                } else {
                  next.character_selection = sel;
                }
                return next;
              })
            }
          />
        )}

        {/* lines 編集 (各 line をカード化、シーン端の line に ▲▼) */}
        <ul className="space-y-2">
          {(scene.lines ?? []).map((line, lIdx) => {
            const flatIdx = flatStartIdx + lIdx;
            const lineCount = scene.lines?.length ?? 0;
            // シーン間移動は端の line でのみ可能 (中央 line を動かすと
            // 後続 line も巻き込むため、誤操作防止に端だけ表示)
            const canMoveUp = lIdx === 0 && sIdx > 0;
            const canMoveDown = lIdx === lineCount - 1 && sIdx < sceneCount - 1;
            return (
              <li key={line._uid ?? lIdx}>
                <div className="rounded-lg border border-slate-700 bg-slate-800/40">
                  <div className="p-3 space-y-3">
                    {/* ヘッダ: #N + ▲▼ + 削除 */}
                    <div className="flex items-center gap-1">
                      <span className="font-mono text-sm text-slate-300 bg-slate-700/40 rounded px-2 py-0.5">
                        #{lIdx + 1}
                      </span>
                      {canMoveUp && (
                        <button
                          type="button"
                          className="text-sm text-slate-400 hover:text-emerald-300 hover:bg-slate-700/60 rounded px-2 py-1 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-slate-400"
                          disabled={boundaryWorking || !ttsReady}
                          onClick={() => onMoveLine(flatIdx, sIdx, sIdx - 1)}
                          title={
                            ttsReady
                              ? "このセリフを前のシーンへ移動 (シーン境界を変更)"
                              : "TTS 完了後に有効"
                          }
                        >
                          ▲
                        </button>
                      )}
                      {canMoveDown && (
                        <button
                          type="button"
                          className="text-sm text-slate-400 hover:text-emerald-300 hover:bg-slate-700/60 rounded px-2 py-1 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-slate-400"
                          disabled={boundaryWorking || !ttsReady}
                          onClick={() => onMoveLine(flatIdx, sIdx, sIdx + 1)}
                          title={
                            ttsReady
                              ? "このセリフを次のシーンへ移動 (シーン境界を変更)"
                              : "TTS 完了後に有効"
                          }
                        >
                          ▼
                        </button>
                      )}
                      <button
                        type="button"
                        className="ml-auto text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-900/20 rounded px-2 py-1"
                        onClick={() => {
                          onSceneChange((s) => {
                            const lines = (s.lines ?? []).slice();
                            lines.splice(lIdx, 1);
                            return { ...s, lines };
                          });
                        }}
                        title="このセリフを削除"
                      >
                        × 削除
                      </button>
                    </div>

                    {/* セリフ (フル幅) — start/end は Stage 2 (TTS) が実音声長から
                        自動計算するので Stage 1 では編集しない */}
                    <label className="block">
                      <span className="text-[11px] text-slate-400 block mb-1">
                        セリフ
                      </span>
                      <textarea
                        className="input font-sans text-sm w-full"
                        rows={2}
                        value={line.text}
                        onChange={(e) => {
                          onSceneChange((s) => {
                            const lines = (s.lines ?? []).slice();
                            lines[lIdx] = {
                              ...lines[lIdx],
                              text: e.target.value,
                            };
                            return { ...s, lines };
                          });
                        }}
                      />
                    </label>

                    {/* メタ: 感情 */}
                    <label className="block">
                      <span className="text-[11px] text-slate-400 block mb-1">
                        感情
                      </span>
                      <select
                        className="select text-xs w-full max-w-xs"
                        value={line.emotion ?? ""}
                        onChange={(e) => {
                          onSceneChange((s) => {
                            const lines = (s.lines ?? []).slice();
                            lines[lIdx] = {
                              ...lines[lIdx],
                              emotion: e.target.value || undefined,
                            };
                            return { ...s, lines };
                          });
                        }}
                      >
                        <option value="">(未指定)</option>
                        {EMOTIONS.map((em) => (
                          <option key={em} value={em}>
                            {em}
                          </option>
                        ))}
                      </select>
                    </label>

                    {/* 話者選択 */}
                    {featuredRefs.length > 0 && (
                      <SpeakerPicker
                        characters={featuredRefs}
                        selected={line.speaker}
                        allScenes={allScenes}
                        onChange={(name) => {
                          onSceneChange((s) => {
                            const lines = (s.lines ?? []).slice();
                            lines[lIdx] = {
                              ...lines[lIdx],
                              speaker: name || undefined,
                            };
                            return { ...s, lines };
                          });
                        }}
                        onBulkApply={onSceneSpeakerBulkApply}
                      />
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
        <button
          className="btn-ghost text-xs"
          onClick={() => {
            onSceneChange((s) => ({
              ...s,
              lines: [
                ...(s.lines ?? []),
                {
                  text: "",
                  start: 0,
                  emotion: "中立",
                  _uid: freshUid(),
                },
              ],
            }));
          }}
        >
          + セリフ追加
        </button>
      </div>
    </div>
  );
}

// collectRawSpeakerResidue / computeDiagnostics は script-edit-utils.ts に
// 移管済 (= §3.1.3-c)。本ファイル冒頭で import + re-export している。

// BaseCharacterCard は ./BaseCharacterCard.tsx に移管済 (= §3.1.3-c)。

// AnalyzeSuggestedBadge は ./AnalyzeSuggestedBadge.tsx に移管済 (= §3.1.3-c)。
// CAMERA_DISTANCE_OPTIONS は script-edit-utils.ts に移管済。
// どちらも本ファイル冒頭で import している。

// LocationPicker は ./LocationPicker.tsx に移管済 (= §3.1.3-c)。
// CameraDistancePicker は ./CameraDistancePicker.tsx に移管済。

/**
 * 動画全体の登場人物を characters/ 配下の画像から選択するセクション。
 * 選択された ref は abstract.featured_characters に保存され、
 * 各シーンの SceneCharacterSelector / SpeakerPicker の候補として使われる。
 */
function FeaturedCharactersSection({
  allRefs,
  selected,
  isExplicit,
  analyzeSuggested,
  onChange,
  onClearExplicit,
}: {
  allRefs: string[];
  /** 表示上アクティブな ref 一覧 (= explicit なら featured_characters、未指定なら fallback list) */
  selected: string[];
  /** abstract.featured_characters が明示的に書かれているか */
  isExplicit: boolean;
  /** analyze が casting 検出を実行したか (= 「✨ analyze 推定」バッジ表示) */
  analyzeSuggested: boolean;
  onChange: (next: string[]) => void;
  onClearExplicit: () => void;
}) {
  const baseGroups = useMemo(() => groupByBase(allRefs), [allRefs]);
  // selected の中で base 単位の選択状態 (= base → 衣装) を抽出。同 base の
  // 重複は禁止 (= 衣装変更で旧 ref は入れ替え)
  const selectedByBase = useMemo(() => {
    const m = new Map<string, string>();
    for (const ref of selected) {
      const { base, wardrobe } = splitRef(ref);
      m.set(base, wardrobe);
    }
    return m;
  }, [selected]);

  if (allRefs.length === 0) {
    return (
      <div className="border border-slate-700 rounded p-2 text-xs text-slate-500">
        characters/ ディレクトリに画像がありません。
      </div>
    );
  }

  const setBase = (baseId: string, wardrobe: string) => {
    const newRef = joinRef(baseId, wardrobe);
    const filtered = selected.filter((r) => splitRef(r).base !== baseId);
    onChange([...filtered, newRef]);
  };
  const clearBase = (baseId: string) => {
    onChange(selected.filter((r) => splitRef(r).base !== baseId));
  };

  return (
    <div className="border border-slate-700 rounded p-2 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-slate-300 font-medium">👥 登場人物</span>
        <span className="text-[11px] text-slate-500">
          被写体ごとに 1 衣装を選択 ({selected.length} 人)
          {!isExplicit && <span className="ml-2 text-amber-400">(未指定)</span>}
        </span>
        {analyzeSuggested && isExplicit && <AnalyzeSuggestedBadge />}
        {isExplicit && (
          <button
            type="button"
            className="ml-auto text-[11px] text-slate-500 hover:text-slate-300"
            onClick={onClearExplicit}
            title="明示指定を解除"
          >
            ⤺ 自動に戻す
          </button>
        )}
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
        {[...baseGroups.entries()].map(([baseId, wardrobes]) => {
          const active = selectedByBase.has(baseId);
          const wardrobe = selectedByBase.get(baseId) ?? wardrobes[0] ?? "";
          return (
            <BaseCharacterCard
              key={baseId}
              baseId={baseId}
              wardrobes={wardrobes}
              selectedWardrobe={wardrobe}
              active={active}
              onSelect={(w) => setBase(baseId, w)}
              onClear={() => clearBase(baseId)}
            />
          );
        })}
      </div>
    </div>
  );
}

/**
 * シーンに登場するキャラを画像カードトグルで指定する。
 *   - selection が undefined: 既定 (compose の自動推論。視覚的には全 active 表示)
 *   - selection が []        : 全 inactive。compose で「人物 0 人」として処理
 *   - selection が [...]     : リスト内のキャラだけ active
 *
 * ボタンクリックで個別 active/inactive を切替。「自動に戻す」ボタンで
 * selection を undefined に戻せる。
 */
function SceneCharacterSelector({
  characters,
  selection,
  onChange,
}: {
  characters: string[];
  selection: string[] | undefined;
  /** null = 自動 (= field 削除)、配列 = 明示指定 */
  onChange: (next: string[] | null) => void;
}) {
  const isExplicit = selection !== undefined;
  const cur = isExplicit ? selection! : characters;
  // 表示は featured で選ばれた被写体のみ。各 base で利用可能な衣装は featured
  // 内で同 base の resolved refs から派生 (= シーン別の衣装変更も featured で
  // 宣言済みのバリアントに限定される)。
  const baseGroups = useMemo(() => groupByBase(characters), [characters]);
  const selectedByBase = useMemo(() => {
    const m = new Map<string, string>();
    for (const ref of cur) {
      const { base, wardrobe } = splitRef(ref);
      m.set(base, wardrobe);
    }
    return m;
  }, [cur]);

  const setBase = (baseId: string, wardrobe: string) => {
    const newRef = joinRef(baseId, wardrobe);
    const filtered = cur.filter((r) => splitRef(r).base !== baseId);
    onChange([...filtered, newRef]);
  };
  const clearBase = (baseId: string) => {
    const next = cur.filter((r) => splitRef(r).base !== baseId);
    // 全 base 解除 = 「明示 0 人」ではなく「自動推論に戻す」が自然な操作。
    // 明示的に 0 人 (= 背景のみ) にしたい場合は別途別 path で実現する想定。
    if (next.length === 0) {
      onChange(null);
      return;
    }
    onChange(next);
  };

  return (
    <div className="space-y-2 border-t border-slate-700/50 pt-2">
      <span className="text-xs text-slate-500 shrink-0">登場人物:</span>
      <div className="flex flex-wrap items-start gap-2">
        {[...baseGroups.entries()].map(([baseId, wardrobes]) => {
          const active = selectedByBase.has(baseId);
          const wardrobe = selectedByBase.get(baseId) ?? wardrobes[0] ?? "";
          return (
            <BaseCharacterCard
              key={baseId}
              baseId={baseId}
              wardrobes={wardrobes}
              selectedWardrobe={wardrobe}
              active={active}
              onSelect={(w) => setBase(baseId, w)}
              onClear={() => clearBase(baseId)}
              size="sm"
            />
          );
        })}
      </div>
      {isExplicit && (
        <button
          type="button"
          className="text-[11px] text-slate-500 hover:text-slate-300 ml-1"
          onClick={() => onChange(null)}
          title="シーン別指定を解除し compose の既定に戻す"
        >
          ⤺ 自動に戻す
        </button>
      )}
      {isExplicit && selection!.length === 0 && (
        <span className="text-[11px] text-amber-400">
          人物 0 (背景のみ生成)
        </span>
      )}
    </div>
  );
}

/**
 * 1 line に対して character/<ref>.png を avatar カードとして並べ、speaker を
/**
 * per-line `line.speaker` から表示用 resolved id を引く resolver。
 *
 * 2026-05-17 schema 撤廃版: line.speaker は resolved id のみを保持する
 * (= 旧 `speaker_to_ref` mapping や raw `speaker_N` 形式は撤廃)。本関数は
 * 単純な passthrough だが、`selected` 未設定時に `siblingSpeakers` (= 同
 * project 内の他 line で実際に使われている speaker 集合) が 1 つだけなら
 * その値を implicit active として表示する。
 *
 * 解決順:
 *   1. `selected` が resolved id (= `f1__office` 等) → そのまま使う
 *   2. `selected` 未設定 + `siblingSpeakers` が 1 種類のみ → 暗黙 active
 *   3. それ以外 → undefined (= active 無し、ユーザに選ばせる)
 */
// resolveLineSpeaker / collectAllLineSpeakers は script-edit-utils.ts に
// 移管済 (= §3.1.3-b)。本ファイル冒頭で import + re-export している。

function SpeakerPicker({
  characters,
  selected,
  allScenes,
  onChange,
  onBulkApply,
}: {
  characters: string[];
  selected: string | undefined;
  /** project の全 scene (= implicit active 判定 + bulk-apply 候補数表示) */
  allScenes: AbstractScreenplay["scenes"];
  onChange: (name: string | undefined) => void;
  /** 同じ「現在 active な speaker」を持つ全 line を newRef に置換する */
  onBulkApply: (oldRef: string, newRef: string) => void;
}) {
  const allSpeakers = useMemo(
    () => collectAllLineSpeakers(allScenes),
    [allScenes],
  );
  const { resolved, implicit } = resolveLineSpeaker(selected, allSpeakers);
  const resolvedBase = resolved ? splitRef(resolved).base : "";
  const resolvedWardrobe = resolved ? splitRef(resolved).wardrobe : "";
  const baseGroups = useMemo(() => groupByBase(characters), [characters]);

  // bulk-apply の候補数: 現在 active な ref を共有する line 数
  // (= 「同 speaker の全 line に適用」ボタンに件数を表示)
  const bulkTargetCount = useMemo(() => {
    if (!resolved) return 0;
    let count = 0;
    for (const sc of allScenes) {
      for (const ln of sc.lines ?? []) {
        if (ln.speaker === resolved) count++;
      }
    }
    return count;
  }, [resolved, allScenes]);

  return (
    <div className="border-t border-slate-700/50 pt-2">
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-[11px] text-slate-400">話者</span>
        <span className="text-[10px] text-slate-500">(1人だけ選択)</span>
        {implicit && resolved && (
          <span
            className="text-[10px] text-slate-400 bg-slate-700/40 rounded px-1.5"
            title={
              `line.speaker 未設定。動画内で他の line が ${resolved} 1 種類` +
              "のみ使っているため自動的にこのキャラを話者として採用しています。" +
              "クリックで明示的に固定できます。"
            }
          >
            自動: {resolved}
          </span>
        )}
        {selected && (
          <button
            type="button"
            className="ml-auto text-[10px] text-slate-500 hover:text-rose-300"
            onClick={() => onChange(undefined)}
            title="話者を未指定に戻す"
          >
            ⤺ クリア
          </button>
        )}
      </div>
      <div role="radiogroup" aria-label="話者" className="flex flex-wrap gap-2">
        {[...baseGroups.entries()].map(([baseId, wardrobes]) => {
          const active = baseId === resolvedBase;
          const wardrobe = active ? resolvedWardrobe : (wardrobes[0] ?? "");
          return (
            <BaseCharacterCard
              key={baseId}
              baseId={baseId}
              wardrobes={wardrobes}
              selectedWardrobe={wardrobe}
              active={active}
              showCheckmark
              onSelect={(w) => {
                const newRef = joinRef(baseId, w);
                if (newRef !== selected) onChange(newRef);
              }}
              size="sm"
            />
          );
        })}
      </div>
      {/* bulk-apply: 同じ speaker を共有する line が 2+ のときだけ表示 */}
      {resolved && bulkTargetCount >= 2 && (
        <div className="mt-2 flex items-center justify-end">
          <button
            type="button"
            className="text-[10px] text-emerald-300 hover:text-emerald-200 hover:bg-emerald-900/30 rounded px-2 py-0.5 border border-emerald-700/40"
            onClick={() => {
              // 現在 active な ref を共有する全 line を resolved に書き換える。
              // 「自動: foo」状態で別キャラに変更したい時の 1 クリック操作。
              const promptText =
                `現在 ${resolved} を話者とする ${bulkTargetCount} line を ` +
                "別キャラに一括変更する場合、変更後のキャラを下のカードで先に選択してください。\n\n" +
                "(= 先にこの行で別カードをクリック → その後で再び本ボタンを押す)";
              if (selected && selected !== resolved) {
                // 既にこの行は別キャラに変更済 → bulk-apply 実行
                onBulkApply(resolved, selected);
              } else {
                window.alert(promptText);
              }
            }}
            title={
              `「${resolved}」を話者とする ${bulkTargetCount} line すべてを、` +
              "この行で選択中のキャラに一括変更します"
            }
          >
            ✓ 同 speaker {bulkTargetCount} line に適用
          </button>
        </div>
      )}
    </div>
  );
}

// Row (= ScriptEditRow) は ./ScriptEditRow.tsx に移管済 (= §3.1.3-c)。
// fmtCost は script-edit-utils.ts に移管済 (= §3.1.3-d)。

// CompletenessBanner は ./CompletenessBanner.tsx に移管済 (= §3.1.3-c)。

// BulkApplyBar は ./BulkApplyBar.tsx に移管済 (= §3.1.3-c)。
