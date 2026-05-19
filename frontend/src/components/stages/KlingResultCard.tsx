// StageKling.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 1 シーン分の Kling 結果カード:
//   - 動画プレビュー (生 raw / trim 後切替)
//   - cached / clip_library hit バッジ
//   - 別 cache 候補の swap UI
//   - 再生成ボタン (= 2 段階確認 + cost preview)

import { useEffect, useState } from "react";

import { api, klingAssetUrl, sceneTrimAssetUrl } from "../../api";
import { useClipLibraryStatus } from "../../hooks/useClipLibraryStatus";
import type { CostMedianRate, KlingSceneDecision, Scene } from "../../types";
import ClipLibraryBadge from "../ClipLibraryBadge";
import ComposedPromptPreview from "../ComposedPromptPreview";
import { CostEstimatePreview } from "../CostEstimatePreview";
import SceneTtsRow from "../SceneTtsRow";
import { useShellCtx } from "../StageGate";
import { formatKlingCost, klingSceneCost } from "./kling-utils";

export function KlingResultCard({
  scene,
  sIdx,
  rate,
}: {
  scene: Scene;
  sIdx: number;
  rate: CostMedianRate | null;
}) {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const [showRaw, setShowRaw] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<KlingSceneDecision | null>(null);
  const [showAlt, setShowAlt] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.klingCache
      .decisions(ts)
      .then((s) => {
        if (!cancelled) {
          setDecision(s.scene_decisions[String(sIdx)] ?? null);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [ts, sIdx, ctx.detail.progress.stages.kling.regen_count]);

  const cost = klingSceneCost(scene.duration, rate);
  const isCached = decision?.decision === "cache";

  // UI 5: clip_library hit 状態のバッジ表示用
  const clipStatus = useClipLibraryStatus(
    ts,
    ctx.detail.progress.stages.kling.regen_count,
  );
  const sceneClipStatus =
    clipStatus.kind === "ready"
      ? clipStatus.data.scenes.find((s) => s.scene_idx === sIdx)
      : undefined;
  const altCandidates =
    (decision?.candidates ?? []).filter(
      (c) => c.key !== decision?.decided_key,
    ) ?? [];

  const onRegen = async () => {
    setSaving(true);
    setError(null);
    try {
      await ctx.regen({ stage: "kling", scene_idx: sIdx });
      setConfirming(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const onSwapToCache = async (key: string) => {
    setSaving(true);
    setError(null);
    try {
      await api.klingCache.useCache(ts, sIdx, key);
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card flex flex-row gap-4 items-start">
      <div className="w-32 sm:w-36 aspect-[9/16] bg-slate-950 overflow-hidden rounded shrink-0">
        <video
          key={`${showRaw ? "raw" : "trim"}-${ctx.detail.progress.stages.kling.regen_count}`}
          src={
            showRaw
              ? klingAssetUrl(
                  ts,
                  sIdx,
                  ctx.detail.progress.stages.kling.regen_count,
                )
              : sceneTrimAssetUrl(
                  ts,
                  sIdx,
                  ctx.detail.progress.stages.kling.regen_count,
                )
          }
          autoPlay
          loop
          muted
          playsInline
          className="w-full h-full object-cover"
        />
      </div>
      <div className="flex-1 min-w-0 space-y-2">
        <div className="flex justify-between items-center text-xs text-slate-400">
          <span className="flex items-center gap-2">
            <span>
              シーン{sIdx + 1} · {scene.duration}s
            </span>
            {isCached && (
              <span className="badge bg-emerald-700 text-emerald-100">
                ♻️ cached
              </span>
            )}
            <ClipLibraryBadge
              status={sceneClipStatus}
              enabled={
                clipStatus.kind === "ready"
                  ? clipStatus.data.enabled
                  : undefined
              }
            />
          </span>
          <button
            className="btn-ghost text-xs"
            onClick={() => setShowRaw((v) => !v)}
            title="生クリップ ↔ trim後を切替"
          >
            {showRaw ? "trim後" : "生raw"}
          </button>
        </div>
        <SceneTtsRow lines={scene.lines ?? []} />
        <ComposedPromptPreview
          ts={ts}
          sceneIdx={sIdx}
          field="animation_prompt"
          version={ctx.detail.progress.stages.kling.regen_count}
        />
        {error && (
          <div className="text-rose-400 text-xs mb-2 mt-2">{error}</div>
        )}
        {altCandidates.length > 0 && (
          <div className="text-xs">
            <button
              className="btn-ghost text-xs"
              onClick={() => setShowAlt((v) => !v)}
            >
              {showAlt
                ? "▼ 別 cache 候補を隠す"
                : `▶ 別 cache 候補 (${altCandidates.length})`}
            </button>
            {showAlt && (
              <div className="mt-2 space-y-2">
                {altCandidates.map((c) => (
                  <div
                    key={c.key}
                    className="flex flex-row gap-2 items-center p-2 rounded bg-slate-900/40"
                  >
                    <video
                      src={api.klingCache.previewUrl(c.key)}
                      autoPlay
                      loop
                      muted
                      playsInline
                      className="w-16 h-28 object-cover rounded"
                    />
                    <div className="flex-1 text-xs space-y-1">
                      <div>
                        適合度 {Math.round(c.fitness * 100)}% / 元 audio{" "}
                        {(c.meta.original_audio_duration ?? 0).toFixed(2)}s
                      </div>
                      <button
                        className="btn-secondary text-xs"
                        disabled={saving}
                        onClick={() => onSwapToCache(c.key)}
                      >
                        ♻️ この候補に切替
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="flex flex-col items-end gap-1">
          {confirming && (
            <CostEstimatePreview
              stage="kling"
              params={{
                duration_sec: scene.duration ?? 0,
                model: "fal-ai/kling-video/v3/standard/image-to-video",
              }}
            />
          )}
          <div className="flex justify-end gap-2">
            {!confirming ? (
              <button
                className="btn-secondary text-xs"
                onClick={() => setConfirming(true)}
              >
                再生成 ({formatKlingCost(cost)})
              </button>
            ) : (
              <>
                <button
                  className="btn-ghost text-xs"
                  onClick={() => setConfirming(false)}
                >
                  キャンセル
                </button>
                <button
                  className="btn-danger text-xs"
                  disabled={saving}
                  onClick={onRegen}
                >
                  {saving
                    ? "実行中..."
                    : `本当に ${formatKlingCost(cost)} 使う`}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
