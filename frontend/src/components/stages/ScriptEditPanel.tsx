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
import { FeaturedCharactersSection } from "./FeaturedCharactersSection";
import { LocationPicker } from "./LocationPicker";
import { SceneCharacterSelector } from "./SceneCharacterSelector";
import { SceneEditor } from "./SceneEditor";
import { ScriptEditRow } from "./ScriptEditRow";
import { SpeakerPicker } from "./SpeakerPicker";

// resolveLineSpeaker / collectRawSpeakerResidue / computeDiagnostics は
// 外部テスト / import で参照されるため re-export を保つ (§3.1.3-c)。
export { collectRawSpeakerResidue, computeDiagnostics, resolveLineSpeaker };

// EMOTIONS は ./SceneEditor.tsx に移管済 (= §3.1.3-c)。
// SceneEditor 内 line.emotion select 専用の定数だったため。

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

// SceneEditor は ./SceneEditor.tsx に移管済 (= §3.1.3-c)。

// collectRawSpeakerResidue / computeDiagnostics は script-edit-utils.ts に
// 移管済 (= §3.1.3-c)。本ファイル冒頭で import + re-export している。

// BaseCharacterCard は ./BaseCharacterCard.tsx に移管済 (= §3.1.3-c)。

// AnalyzeSuggestedBadge は ./AnalyzeSuggestedBadge.tsx に移管済 (= §3.1.3-c)。
// CAMERA_DISTANCE_OPTIONS は script-edit-utils.ts に移管済。
// どちらも本ファイル冒頭で import している。

// LocationPicker は ./LocationPicker.tsx に移管済 (= §3.1.3-c)。
// CameraDistancePicker は ./CameraDistancePicker.tsx に移管済。

// FeaturedCharactersSection は ./FeaturedCharactersSection.tsx に移管済 (= §3.1.3-c)。

// SceneCharacterSelector は ./SceneCharacterSelector.tsx に移管済 (= §3.1.3-c)。

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
// SpeakerPicker は ./SpeakerPicker.tsx に移管済 (= §3.1.3-c)。

// Row (= ScriptEditRow) は ./ScriptEditRow.tsx に移管済 (= §3.1.3-c)。
// fmtCost は script-edit-utils.ts に移管済 (= §3.1.3-d)。

// CompletenessBanner は ./CompletenessBanner.tsx に移管済 (= §3.1.3-c)。

// BulkApplyBar は ./BulkApplyBar.tsx に移管済 (= §3.1.3-c)。
