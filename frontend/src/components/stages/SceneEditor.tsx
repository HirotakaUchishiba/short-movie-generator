// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
//
// 1 シーン分の編集パネル。ヘッダ (シーン#N + 追加 / 削除) +
// 個別設定 (背景 / カメラ距離 / 動き) + 登場人物セレクタ +
// lines (各 line のセリフ / 感情 / 話者) を 1 つにまとめる。

import type { AbstractScreenplay } from "../../types";
import { freshUid } from "../../uid";
import { AnalyzeSuggestedBadge } from "./AnalyzeSuggestedBadge";
import { CameraDistancePicker } from "./CameraDistancePicker";
import { LocationPicker } from "./LocationPicker";
import { SceneCharacterSelector } from "./SceneCharacterSelector";
import { SpeakerPicker } from "./SpeakerPicker";

// SceneEditor 内 line.emotion select の選択肢。
// config.EMOTION_AUDIO_TAGS の key と同じ集合 (= 自動 tag 補完が効く範囲)。
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

export function SceneEditor({
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
