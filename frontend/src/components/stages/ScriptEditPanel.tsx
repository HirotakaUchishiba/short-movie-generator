import { useEffect, useMemo, useState } from "react";
import { useShellCtx } from "../StageGate";
import {
  api,
  characterAssetUrl,
  locationPreviewUrl,
  referenceVideoAssetUrl,
} from "../../api";
import type {
  AbstractDiagnostics,
  AbstractScreenplay,
  AnalyzeJobDetail,
} from "../../types";
import { freshUid } from "../../uid";

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
 * 各シーンの location_ref / camera_distance / animation_style /
 * character_selection / lines (text・emotion・speaker) を編集し、
 * snapshot を abstract のまま PUT する (= live derivation で Stage 2 以降が
 * 都度 compose を走らせる)。
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
  const [locationIds, setLocationIds] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [boundaryWorking, setBoundaryWorking] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.getAnalyzeJob(jobId),
      api.getProjectAbstract(ts),
      api.listCharacters(),
      api.listLocations(),
    ])
      .then(([j, ab, chars, locs]) => {
        if (cancelled) return;
        setJob(j);
        setAbstract(ab.abstract);
        setCharacterRefs(chars.characters);
        setLocationIds(locs.locations.map((l) => l.id));
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

  // 全シーンに同じ値を一括適用する。location_ref / camera_distance /
  // animation_style の 3 種に対応 (= 17 シーンクリックの繰り返し回避)。
  type BulkField = "location_ref" | "camera_distance" | "animation_style";
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

  return (
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
        <BulkApplyBar locationIds={locationIds} onApply={applyToAllScenes} />

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

        {/* 🎙 話者マッピング (= multi-speaker 動画でのみ表示) */}
        <SpeakerMappingSection
          rawSpeakers={collectRawSpeakers(abstract)}
          allRefs={characterRefs}
          mapping={
            (abstract.speaker_to_ref as Record<string, string> | undefined) ??
            {}
          }
          onChange={(speaker, ref) => {
            const cur =
              (abstract.speaker_to_ref as Record<string, string> | undefined) ??
              {};
            const nextMap = { ...cur };
            if (ref) {
              nextMap[speaker] = ref;
            } else {
              delete nextMap[speaker];
            }
            const featuredCur = Array.isArray(abstract.featured_characters)
              ? abstract.featured_characters
              : [];
            // 同 base の既存 ref は新 ref で置換 (= featured 重複禁止)。
            // FeaturedCharactersSection と挙動を揃える。
            const nextFeatured = ref
              ? [
                  ...featuredCur.filter(
                    (r) => splitRef(r).base !== splitRef(ref).base,
                  ),
                  ref,
                ]
              : featuredCur;
            setAbstract({
              ...abstract,
              speaker_to_ref: nextMap,
              featured_characters: nextFeatured,
            });
            setDirty(true);
          }}
        />

        <p className="text-[11px] text-slate-500 leading-relaxed">
          ※ 各シーンの先頭セリフの <strong>▲</strong> / 末尾セリフの{" "}
          <strong>▼</strong> を押すと隣のシーンへ移動できます (順序保持のため ±1
          シーンのみ)。 テキスト・順序は不変なので ElevenLabs
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
              locationIds={locationIds}
              featuredRefs={
                Array.isArray(abstract.featured_characters)
                  ? abstract.featured_characters
                  : []
              }
              speakerToRef={
                (abstract.speaker_to_ref as
                  | Record<string, string>
                  | undefined) ?? {}
              }
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
            disabled={!dirty || status === "saving" || !abstract.caption.trim()}
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
            <Row label="job id" value={job.id} mono />
            <Row label="status" value={job.status} />
            <Row
              label="video sha256"
              value={`${job.video_sha256.slice(0, 16)}…`}
              mono
            />
            <Row label="cost (実)" value={fmtCost(job.actual_cost_usd)} />
            <Row label="finished at" value={job.finished_at ?? "—"} />
          </dl>
        </div>
      </details>
    </div>
  );
}

function SceneEditor({
  sIdx,
  scene,
  locationIds,
  featuredRefs,
  speakerToRef,
  flatStartIdx,
  sceneCount,
  boundaryWorking,
  ttsReady,
  onSceneChange,
  onMoveLine,
  onAddSceneAfter,
  onDeleteScene,
}: {
  sIdx: number;
  scene: AbstractScreenplay["scenes"][number];
  locationIds: string[];
  featuredRefs: string[];
  speakerToRef: Record<string, string>;
  flatStartIdx: number;
  sceneCount: number;
  boundaryWorking: boolean;
  ttsReady: boolean;
  onSceneChange: (
    fn: (
      s: AbstractScreenplay["scenes"][number],
    ) => AbstractScreenplay["scenes"][number],
  ) => void;
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
        {/* 背景 / カメラ距離 / アニメーション (シーン個別設定) */}
        <div className="space-y-2 text-xs">
          <LocationPicker
            locationIds={locationIds}
            scene={scene}
            onSceneChange={onSceneChange}
          />

          <CameraDistancePicker scene={scene} onSceneChange={onSceneChange} />

          <div className="bg-slate-800/40 rounded p-2">
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
                        speakerToRef={speakerToRef}
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

// ─── 背景セレクタ (= ロケ ID カード) ──────────────────────────
// 各シーンが独立して location_ref を持つ。候補は locations/<id>.json 全体。
function LocationCard({
  id,
  active,
  onClick,
}: {
  id: string;
  active: boolean;
  onClick: () => void;
}) {
  const [hasPreview, setHasPreview] = useState(true);

  return (
    <button
      type="button"
      className={`relative flex flex-col items-center rounded border overflow-hidden transition ${
        active
          ? "border-emerald-500 bg-emerald-900/30 text-emerald-200"
          : "border-slate-700 bg-slate-900/40 text-slate-400 opacity-70 hover:opacity-100"
      }`}
      onClick={onClick}
      title={active ? `${id} を解除` : `${id} を選択`}
    >
      {hasPreview ? (
        <img
          src={locationPreviewUrl(id)}
          alt={id}
          className={`w-full aspect-[9/16] object-cover ${
            active ? "" : "grayscale"
          }`}
          onError={() => setHasPreview(false)}
        />
      ) : (
        <div className="w-full aspect-[9/16] flex items-center justify-center bg-slate-900/60 text-[10px] text-slate-500 px-1 text-center">
          <span>(プレビュー無し)</span>
        </div>
      )}
      <span className="text-[11px] py-1 px-1 truncate w-full text-center">
        {id}
      </span>
    </button>
  );
}

function LocationPicker({
  locationIds,
  scene,
  onSceneChange,
}: {
  locationIds: string[];
  scene: AbstractScreenplay["scenes"][number];
  onSceneChange: (
    fn: (
      s: AbstractScreenplay["scenes"][number],
    ) => AbstractScreenplay["scenes"][number],
  ) => void;
}) {
  const value = scene.location_ref ?? "";

  if (locationIds.length === 0) {
    return (
      <div className="bg-slate-800/40 rounded p-2 text-xs text-slate-500">
        背景: locations/ にロケが登録されていません
      </div>
    );
  }
  const setLoc = (id: string) => {
    onSceneChange((s) => {
      const next = { ...s };
      if (id === value) {
        delete (next as Record<string, unknown>).location_ref;
      } else {
        next.location_ref = id;
      }
      return next;
    });
  };
  return (
    <div className="bg-slate-800/40 rounded p-2 space-y-2">
      <span className="text-slate-300 font-medium text-xs">背景</span>
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
        {locationIds.map((id) => {
          const active = id === value;
          return (
            <LocationCard
              key={id}
              id={id}
              active={active}
              onClick={() => setLoc(id)}
            />
          );
        })}
      </div>
    </div>
  );
}

const _CAMERA_DISTANCES = [
  { id: "close-up", label: "close-up", desc: "顔寄り" },
  { id: "medium-close", label: "medium-close", desc: "胸〜顔" },
  { id: "medium", label: "medium", desc: "腰〜顔" },
  { id: "wide", label: "wide", desc: "全身" },
] as const;

// ─── カメラ距離セレクタ (= カード) ──────────────────────────
function CameraDistancePicker({
  scene,
  onSceneChange,
}: {
  scene: AbstractScreenplay["scenes"][number];
  onSceneChange: (
    fn: (
      s: AbstractScreenplay["scenes"][number],
    ) => AbstractScreenplay["scenes"][number],
  ) => void;
}) {
  const value = scene.camera_distance ?? "";
  const setVal = (id: string) => {
    onSceneChange((s) => {
      const next = { ...s };
      if (id === value || !id) {
        delete next.camera_distance;
      } else {
        next.camera_distance = id as NonNullable<typeof next.camera_distance>;
      }
      return next;
    });
  };
  return (
    <div className="bg-slate-800/40 rounded p-2 space-y-2">
      <span className="text-slate-300 font-medium text-xs">カメラ距離</span>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {_CAMERA_DISTANCES.map((c) => {
          const active = c.id === value;
          return (
            <button
              key={c.id}
              type="button"
              className={`flex flex-col items-center justify-center rounded border p-2 transition text-[11px] ${
                active
                  ? "border-emerald-500 bg-emerald-900/30 text-emerald-200"
                  : "border-slate-700 bg-slate-900/40 text-slate-400 opacity-60 hover:opacity-100"
              }`}
              onClick={() => setVal(c.id)}
              title={active ? `${c.id} を解除` : `${c.id} を選択`}
            >
              <img
                src={`/camera-distance/${c.id}.png`}
                alt={c.label}
                className={`w-12 h-20 mb-1 rounded object-cover ${
                  active ? "" : "opacity-70"
                }`}
              />
              <span className="font-medium">{c.label}</span>
              <span className="text-[10px] text-slate-500">{c.desc}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * 抽象台本に出てくる匿名 speaker_N を全シーンから集めて返す。
 * 出現回数とシーン数も同時に算出し、UI のヒント表示に使う。
 * 既に ref に解決済み (= ユーザが個別 override した) speaker は除外する。
 */
function collectRawSpeakers(
  abstract: AbstractScreenplay,
): { id: string; lines: number; scenes: number }[] {
  const lineCount = new Map<string, number>();
  const sceneSet = new Map<string, Set<number>>();
  for (let sIdx = 0; sIdx < abstract.scenes.length; sIdx++) {
    for (const line of abstract.scenes[sIdx].lines ?? []) {
      const sp = line.speaker;
      if (!sp || !/^speaker_\d+$/i.test(sp)) continue;
      lineCount.set(sp, (lineCount.get(sp) ?? 0) + 1);
      if (!sceneSet.has(sp)) sceneSet.set(sp, new Set());
      sceneSet.get(sp)!.add(sIdx);
    }
  }
  return [...lineCount.keys()].sort().map((id) => ({
    id,
    lines: lineCount.get(id) ?? 0,
    scenes: sceneSet.get(id)?.size ?? 0,
  }));
}

// ─── 被写体 (base) × 衣装 (wardrobe) の解決ヘルパー ─────────

/** resolved id (= `"<base>__<wardrobe>"` or `"<base>"`) を分解する。 */
function splitRef(ref: string): { base: string; wardrobe: string } {
  const i = ref.indexOf("__");
  return i < 0
    ? { base: ref, wardrobe: "" }
    : { base: ref.slice(0, i), wardrobe: ref.slice(i + 2) };
}

/** base + wardrobe を resolved id に再合成する (`wardrobe === ""` なら base 単独)。 */
function joinRef(base: string, wardrobe: string): string {
  return wardrobe ? `${base}__${wardrobe}` : base;
}

/** resolved refs を base 単位にグルーピングし、各 base の利用可能 wardrobes
 *  list を返す (`""` = base.png 単独)。base の登場順を保ち、wardrobe は昇順。 */
function groupByBase(refs: string[]): Map<string, string[]> {
  const out = new Map<string, Set<string>>();
  for (const ref of refs) {
    const { base, wardrobe } = splitRef(ref);
    if (!out.has(base)) out.set(base, new Set());
    out.get(base)!.add(wardrobe);
  }
  const result = new Map<string, string[]>();
  for (const [base, set] of out) {
    result.set(base, [...set].sort());
  }
  return result;
}

const wardrobeLabel = (w: string) => w || "base";

const _CAMERA_DISTANCE_SET = new Set([
  "close-up",
  "medium-close",
  "medium",
  "wide",
]);

/**
 * frontend 側で abstract から `AbstractDiagnostics` を再計算する。
 * `analyze.compose.diagnose_abstract` (Python) と挙動を合わせる必要がある。
 *
 * `availableCharacters` は `api.listCharacters()` から取れる resolved id の配列。
 * 空配列なら character ref 物理存在検証はスキップ (= テスト・初期化中の挙動と
 * server 側 conftest のスタブと同等)。
 */
function computeDiagnostics(
  abstract: AbstractScreenplay,
  availableCharacters: string[],
): AbstractDiagnostics {
  const speakerToRef =
    (abstract.speaker_to_ref as Record<string, string> | undefined) ?? {};
  const featured = (abstract.featured_characters ?? []).filter(
    (c): c is string => typeof c === "string" && !!c,
  );
  const availableSet = new Set(availableCharacters);
  const skipCharCheck = availableSet.size === 0;
  const isUnknownRef = (ref: unknown): ref is string =>
    !skipCharCheck &&
    typeof ref === "string" &&
    ref !== "" &&
    !availableSet.has(ref);

  const unmapped = new Set<string>();
  const scenesWithoutLocation: number[] = [];
  const scenesWithoutCharacters: number[] = [];
  const invalidCamera: { scene_idx: number; value: string }[] = [];
  const unknown = {
    featured: [] as string[],
    speaker_to_ref: [] as { speaker: string; ref: string }[],
    character_selection: [] as { scene_idx: number; ref: string }[],
    speaker: [] as { scene_idx: number; line_idx: number; ref: string }[],
  };

  for (const ref of featured) {
    if (isUnknownRef(ref)) unknown.featured.push(ref);
  }
  for (const [k, v] of Object.entries(speakerToRef)) {
    if (isUnknownRef(v)) unknown.speaker_to_ref.push({ speaker: k, ref: v });
  }

  abstract.scenes.forEach((scene, sIdx) => {
    if (!scene.location_ref) scenesWithoutLocation.push(sIdx);

    const cd = scene.camera_distance;
    if (cd != null && !_CAMERA_DISTANCE_SET.has(cd)) {
      invalidCamera.push({ scene_idx: sIdx, value: cd });
    }

    const sel = scene.character_selection;
    if (Array.isArray(sel)) {
      for (const ref of sel) {
        if (isUnknownRef(ref)) {
          unknown.character_selection.push({ scene_idx: sIdx, ref });
        }
      }
    }

    (scene.lines ?? []).forEach((line, lIdx) => {
      const sp = line.speaker;
      if (!sp || typeof sp !== "string") return;
      // raw 匿名 ID (= speaker_N+) は collectRawSpeakers と同じ正規表現で
      // 判定する。speaker_xyz のような変則値は ref 扱いになり物理存在検証へ。
      if (/^speaker_\d+$/i.test(sp)) {
        if (!(sp in speakerToRef)) unmapped.add(sp);
        return;
      }
      if (isUnknownRef(sp)) {
        unknown.speaker.push({ scene_idx: sIdx, line_idx: lIdx, ref: sp });
      }
    });

    // シーン人物推論を再現して 0 人になるかチェック。
    // featured が空のとき (= 動画全体が「人物無し」の意図) は警告抑制し、
    // false-positive を避ける (= 別途 featuredEmpty 警告で気付ける)。
    if ("character_selection" in scene) {
      if (Array.isArray(sel) && sel.length === 0 && featured.length > 0) {
        scenesWithoutCharacters.push(sIdx);
      }
      return;
    }
    if (featured.length === 0) return;
    const speakers = new Set<string>();
    for (const line of scene.lines ?? []) {
      if (line.speaker) speakers.add(line.speaker);
    }
    const resolved = new Set<string>();
    for (const sp of speakers) {
      const ref = speakerToRef[sp] ?? (featured.includes(sp) ? sp : null);
      if (ref) resolved.add(ref);
    }
    if (resolved.size === 0) {
      scenesWithoutCharacters.push(sIdx);
    }
  });

  return {
    unmapped_speakers: [...unmapped].sort(),
    scenes_without_location: scenesWithoutLocation,
    scenes_without_characters: scenesWithoutCharacters,
    invalid_camera_distance: invalidCamera,
    unknown_character_refs: unknown,
  };
}

/**
 * 被写体 (base) を 1 枚カード化し、内部 select で衣装を切替する共通カード。
 *
 * - 画像クリック → active なら `onClear`、非 active なら
 *   `onSelect(selectedWardrobe)` で active 化
 * - 衣装 select 変更 → `onSelect(newWardrobe)` (= active 化しつつ衣装更新)
 *
 * `selectedWardrobe` は active 時 = 現在の衣装、非 active 時 = カードのプレビュー
 * 用衣装 (= 利用可能な衣装の先頭)。利用可能衣装が 1 つだけならドロップダウンを
 * 出さず static 表示。
 */
function BaseCharacterCard({
  baseId,
  wardrobes,
  selectedWardrobe,
  active,
  showCheckmark = false,
  onSelect,
  onClear,
  size = "md",
}: {
  baseId: string;
  wardrobes: string[];
  selectedWardrobe: string;
  active: boolean;
  showCheckmark?: boolean;
  onSelect: (wardrobe: string) => void;
  onClear?: () => void;
  size?: "md" | "sm";
}) {
  const previewRef = joinRef(baseId, selectedWardrobe);
  const widthCls = size === "sm" ? "w-16" : "w-full";
  const handleCardClick = () => {
    if (active && onClear) onClear();
    else onSelect(selectedWardrobe);
  };
  return (
    <div
      className={`relative flex flex-col items-stretch rounded-lg border-2 overflow-hidden transition ${widthCls} ${
        active
          ? "border-emerald-500 bg-emerald-900/30"
          : "border-slate-700 bg-slate-900/40 opacity-60 hover:opacity-100"
      }`}
    >
      <button
        type="button"
        onClick={handleCardClick}
        className="relative block w-full text-left"
        title={
          active
            ? `${baseId} を解除`
            : `${joinRef(baseId, selectedWardrobe)} を選択`
        }
      >
        {showCheckmark && active && (
          <span
            className="absolute top-1 right-1 w-4 h-4 bg-emerald-500 text-slate-900 text-[10px] font-bold rounded-full flex items-center justify-center z-10"
            aria-hidden
          >
            ✓
          </span>
        )}
        <img
          src={characterAssetUrl(previewRef)}
          alt={previewRef}
          className={`w-full aspect-[9/16] object-cover bg-slate-900 ${
            active ? "" : "grayscale"
          }`}
          onError={(e) => {
            (e.target as HTMLImageElement).style.opacity = "0.2";
          }}
        />
        <div
          className={`text-[11px] py-0.5 px-1 truncate w-full text-center ${
            active ? "text-emerald-200 font-semibold" : "text-slate-400"
          }`}
        >
          {baseId}
        </div>
      </button>
      <div className="px-1 pb-1">
        {wardrobes.length > 1 ? (
          <select
            className="text-[10px] w-full py-0.5 px-1 bg-slate-900/60 border border-slate-700 rounded text-slate-300"
            value={selectedWardrobe}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => onSelect(e.target.value)}
            title="衣装を変更"
          >
            {wardrobes.map((w) => (
              <option key={w || "_base"} value={w}>
                {wardrobeLabel(w)}
              </option>
            ))}
          </select>
        ) : (
          <div className="text-[10px] text-slate-500 truncate w-full text-center py-0.5">
            {wardrobeLabel(selectedWardrobe)}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * analyze で検出された匿名 speaker_N を実 character ref にマッピングする。
 * ここを 1 回設定するだけで、各 line の話者と各シーンの登場人物が compose で
 * 自動的に決まる (= multi-speaker 動画の入力 UX の核)。
 */
function SpeakerMappingSection({
  rawSpeakers,
  allRefs,
  mapping,
  onChange,
}: {
  rawSpeakers: { id: string; lines: number; scenes: number }[];
  allRefs: string[];
  mapping: Record<string, string>;
  onChange: (speaker: string, ref: string | null) => void;
}) {
  const baseGroups = useMemo(() => groupByBase(allRefs), [allRefs]);
  if (rawSpeakers.length === 0) return null;
  if (allRefs.length === 0) {
    return (
      <div className="border border-slate-700 rounded p-2 text-xs text-slate-500">
        🎙 話者マッピング: characters/ ディレクトリに画像がありません。
      </div>
    );
  }
  return (
    <div className="border border-slate-700 rounded p-2 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-slate-300 font-medium">🎙 話者マッピング</span>
        <span className="text-[11px] text-slate-500">
          検出された話者 {rawSpeakers.length} 名 — 各話者を演じる被写体を選択
          (衣装はカード内で切替)
        </span>
      </div>
      <div className="space-y-3">
        {rawSpeakers.map((sp) => {
          const selectedRef = mapping[sp.id];
          const selectedBase = selectedRef ? splitRef(selectedRef).base : "";
          const selectedWardrobe = selectedRef
            ? splitRef(selectedRef).wardrobe
            : "";
          return (
            <div key={sp.id} className="bg-slate-800/40 rounded p-2 space-y-2">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-emerald-300 text-sm">
                  {sp.id}
                </span>
                <span className="text-[11px] text-slate-500">
                  {sp.lines} セリフ / {sp.scenes} シーンに登場
                </span>
                {selectedRef && (
                  <button
                    type="button"
                    className="ml-auto text-[10px] text-slate-500 hover:text-rose-300"
                    onClick={() => onChange(sp.id, null)}
                    title="マッピングをクリア"
                  >
                    ⤺ クリア
                  </button>
                )}
              </div>
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
                {[...baseGroups.entries()].map(([baseId, wardrobes]) => {
                  const active = baseId === selectedBase;
                  const wardrobe = active
                    ? selectedWardrobe
                    : (wardrobes[0] ?? "");
                  return (
                    <BaseCharacterCard
                      key={baseId}
                      baseId={baseId}
                      wardrobes={wardrobes}
                      selectedWardrobe={wardrobe}
                      active={active}
                      onSelect={(w) => onChange(sp.id, joinRef(baseId, w))}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * 動画全体の登場人物を characters/ 配下の画像から選択するセクション。
 * 選択された ref は abstract.featured_characters に保存され、
 * 各シーンの SceneCharacterSelector / SpeakerPicker の候補として使われる。
 */
function FeaturedCharactersSection({
  allRefs,
  selected,
  isExplicit,
  onChange,
  onClearExplicit,
}: {
  allRefs: string[];
  /** 表示上アクティブな ref 一覧 (= explicit なら featured_characters、未指定なら fallback list) */
  selected: string[];
  /** abstract.featured_characters が明示的に書かれているか */
  isExplicit: boolean;
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
 * 視覚的に選択させる。**単一選択** で、active 再クリックでは解除しない。
 * 解除したい場合は別途「⤺ クリア」ボタンを使う。
 *
 * `selected` が `speaker_1` のような raw 匿名 ID の場合は `speakerToRef` で
 * resolve し、その ref のカードをハイライトする (= 話者マッピング経由の
 * デフォルト表示)。ユーザがカードをクリックすると ref で直接上書きされ、
 * raw の連結は切れる (= 個別 override)。
 */
function SpeakerPicker({
  characters,
  selected,
  speakerToRef,
  onChange,
}: {
  characters: string[];
  selected: string | undefined;
  speakerToRef: Record<string, string>;
  onChange: (name: string | undefined) => void;
}) {
  const isRaw = !!selected && /^speaker_\d+$/i.test(selected);
  const resolved = isRaw ? speakerToRef[selected!] : selected;
  const resolvedBase = resolved ? splitRef(resolved).base : "";
  const resolvedWardrobe = resolved ? splitRef(resolved).wardrobe : "";
  const baseGroups = useMemo(() => groupByBase(characters), [characters]);
  return (
    <div className="border-t border-slate-700/50 pt-2">
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-[11px] text-slate-400">話者</span>
        <span className="text-[10px] text-slate-500">(1人だけ選択)</span>
        {isRaw && (
          <span
            className="text-[10px] text-amber-300 bg-amber-900/30 rounded px-1.5"
            title={
              resolved
                ? `話者マッピング: ${selected} → ${resolved}`
                : `${selected} は未マッピング (上のセクションで割当て)`
            }
          >
            🎙 {selected}
            {resolved ? ` → ${resolved}` : " (未マッピング)"}
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
    </div>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex gap-2">
      <dt className="text-slate-500 w-28 shrink-0">{label}</dt>
      <dd className={mono ? "font-mono text-slate-300" : "text-slate-300"}>
        {value}
      </dd>
    </div>
  );
}

function fmtCost(c: number | null | undefined): string {
  if (c == null) return "—";
  return `$${c.toFixed(4)}`;
}

/**
 * compose の不整合をユーザに見せる警告バナー。
 * すべての項目がクリーンなら緑、1 つでも問題があれば琥珀色で警告表示。
 * frontend が abstract / characterRefs から live 計算した diagnostics を
 * 受け取って、未マッピング speaker / location 未設定 / 人物 0 人 / 不正
 * camera_distance / 未定義キャラ ref を一覧化する。
 */
function CompletenessBanner({
  diag,
  captionEmpty,
  featuredEmpty,
}: {
  diag: AbstractDiagnostics;
  captionEmpty: boolean;
  featuredEmpty: boolean;
}) {
  const issues: string[] = [];
  if (captionEmpty) issues.push("caption が空");
  if (featuredEmpty) issues.push("動画全体の登場人物が未指定");
  if (diag.unmapped_speakers.length > 0) {
    issues.push(`未マッピング話者: ${diag.unmapped_speakers.join(", ")}`);
  }
  if (diag.scenes_without_location.length > 0) {
    const ids = diag.scenes_without_location.map((i) => `#${i + 1}`).join(", ");
    issues.push(
      `背景未設定 ${diag.scenes_without_location.length} シーン (${ids})`,
    );
  }
  if (diag.scenes_without_characters.length > 0) {
    const ids = diag.scenes_without_characters
      .map((i) => `#${i + 1}`)
      .join(", ");
    issues.push(
      `人物 0 人 ${diag.scenes_without_characters.length} シーン (${ids})`,
    );
  }
  if (diag.invalid_camera_distance.length > 0) {
    const t = diag.invalid_camera_distance
      .map((x) => `#${x.scene_idx + 1}=${x.value}`)
      .join(", ");
    issues.push(`不正カメラ距離: ${t}`);
  }
  const u = diag.unknown_character_refs;
  if (u) {
    if (u.featured.length > 0) {
      issues.push(`未定義キャラ (登場人物): ${u.featured.join(", ")}`);
    }
    if (u.speaker_to_ref.length > 0) {
      const t = u.speaker_to_ref.map((x) => `${x.speaker}→${x.ref}`).join(", ");
      issues.push(`未定義キャラ (話者マッピング): ${t}`);
    }
    if (u.character_selection.length > 0) {
      const t = u.character_selection
        .map((x) => `#${x.scene_idx + 1}=${x.ref}`)
        .join(", ");
      issues.push(`未定義キャラ (シーン登場人物): ${t}`);
    }
    if (u.speaker.length > 0) {
      const t = u.speaker
        .map((x) => `#${x.scene_idx + 1}/L${x.line_idx + 1}=${x.ref}`)
        .join(", ");
      issues.push(`未定義キャラ (line.speaker): ${t}`);
    }
  }
  if (issues.length === 0) {
    return (
      <div className="rounded p-2 text-xs bg-emerald-900/30 text-emerald-200 border border-emerald-500/40">
        ✅ 抽象台本に未解決の不整合はありません (compose 入力 OK)
      </div>
    );
  }
  return (
    <div className="rounded p-2 text-xs bg-amber-900/30 text-amber-100 border border-amber-500/40">
      <div className="font-semibold mb-1">
        ⚠️ {issues.length} 件の未解決項目があります (このまま compose すると
        意図と違う結果になる可能性):
      </div>
      <ul className="list-disc list-inside space-y-0.5">
        {issues.map((m) => (
          <li key={m}>{m}</li>
        ))}
      </ul>
    </div>
  );
}

const _BULK_CAMERA = ["close-up", "medium-close", "medium", "wide"] as const;
const _BULK_ANIM = ["subtle", "standard", "expressive"] as const;

/**
 * 全シーンに同じ値を一括適用するセレクタ群。
 * 17 シーンクリック地獄を回避するため、location / camera_distance /
 * animation_style の 3 種をまとめて bulk apply できる。
 */
function BulkApplyBar({
  locationIds,
  onApply,
}: {
  locationIds: string[];
  onApply: (
    field: "location_ref" | "camera_distance" | "animation_style",
    value: string | undefined,
  ) => void;
}) {
  const [locVal, setLocVal] = useState("");
  const [camVal, setCamVal] = useState("");
  const [animVal, setAnimVal] = useState("");
  return (
    <div className="border border-slate-700 rounded p-2 space-y-2 bg-slate-800/30">
      <span className="text-[11px] text-slate-400 block">
        🪄 全シーンに一括適用 (個別シーンの値を上書きします)
      </span>
      <div className="flex flex-wrap gap-3 text-xs items-center">
        <label className="flex items-center gap-1">
          <span className="text-slate-500 shrink-0">背景</span>
          <select
            className="select text-xs"
            value={locVal}
            onChange={(e) => {
              const v = e.target.value;
              if (v) onApply("location_ref", v);
              setLocVal("");
            }}
          >
            <option value="">(選んで適用)</option>
            {locationIds.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <span className="text-slate-500 shrink-0">カメラ距離</span>
          <select
            className="select text-xs"
            value={camVal}
            onChange={(e) => {
              const v = e.target.value;
              if (v) onApply("camera_distance", v);
              setCamVal("");
            }}
          >
            <option value="">(選んで適用)</option>
            {_BULK_CAMERA.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <span className="text-slate-500 shrink-0">動き</span>
          <select
            className="select text-xs"
            value={animVal}
            onChange={(e) => {
              const v = e.target.value;
              if (v) onApply("animation_style", v);
              setAnimVal("");
            }}
          >
            <option value="">(選んで適用)</option>
            {_BULK_ANIM.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
