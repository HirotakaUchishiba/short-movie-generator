// Stage 4: Kling 動画。
// 未生成: CacheDecisionFlow (= scan / 判断 / 残りを生成)。
// 生成済み: 各シーンの動画 + per-scene 再生成。
import { useEffect, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api, klingAssetUrl, sceneTrimAssetUrl } from "../../api";
import ComposedPromptPreview from "../ComposedPromptPreview";
import SceneTtsRow from "../SceneTtsRow";
import ClipLibraryBadge from "../ClipLibraryBadge";
import CacheDecisionFlow from "../cache/CacheDecisionFlow";
import { CostEstimatePreview } from "../CostEstimatePreview";
import type { CachePresenter, SceneContext } from "../cache/types";
import { useClipLibraryStatus } from "../../hooks/useClipLibraryStatus";
import type {
  CostMedianRate,
  KlingCandidateMeta,
  KlingSceneDecision,
  Scene,
} from "../../types";
import { useCostMedianRate } from "../../useCostMedianRate";
import { BulkKlingRegenBar } from "./BulkKlingRegenBar";
import { KlingResultCard } from "./KlingResultCard";
import { klingSceneCost } from "./kling-utils";

export default function StageKling() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const generated = !!ctx.detail.progress.stages.kling.generated_at;

  return (
    <StageGate
      stage="kling"
      title="Kling動画"
      description="cache スキャン → シーンごとに『キャッシュ採用 / 新規生成』を判断 → 残りを一括生成。最高額のステージなので慎重に。"
    >
      {generated ? (
        <KlingResultsView />
      ) : (
        <KlingDecisionFlow
          ts={ctx.detail.timestamp}
          sceneCount={sp.scenes.length}
        />
      )}
    </StageGate>
  );
}

// ───────────── 判断前 (= 自動 scan + per-scene 判断) ─────────────

function KlingDecisionFlow({
  ts,
  sceneCount,
}: {
  ts: string;
  sceneCount: number;
}) {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const { rate: klingRate } = useCostMedianRate(
    "kling",
    ctx.serverConfig.cost_models.kling,
  );

  const presenter: CachePresenter<KlingCandidateMeta> = {
    renderPreview: (key) => (
      <video
        src={api.klingCache.previewUrl(key)}
        autoPlay
        loop
        muted
        playsInline
        className="w-full h-full object-cover"
      />
    ),
    renderCandidateMeta: (meta, ctx2) => {
      const orig = meta.original_audio_duration ?? null;
      const newAudio = ctx2.newAudioDuration;
      const diffPct =
        orig != null && newAudio != null && orig > 0
          ? ((newAudio - orig) / orig) * 100
          : null;
      return (
        <div className="text-slate-400 space-y-0.5">
          <div>
            元 audio:{" "}
            <span className="font-mono text-slate-300">
              {orig != null ? orig.toFixed(2) : "?"}
            </span>
            s
            {newAudio != null && (
              <>
                {" "}
                / 新 audio:{" "}
                <span className="font-mono text-slate-300">
                  {newAudio.toFixed(2)}
                </span>
                s
                {diffPct != null && (
                  <span className="ml-1">({diffPct.toFixed(0)}%)</span>
                )}
              </>
            )}
          </div>
          <div className="text-slate-500">
            location: {meta.location_ref ?? "-"} / camera:{" "}
            {meta.camera_distance ?? "-"} / hits: {meta.hit_count ?? 0}
            {meta.quality?.final_render_completed && (
              <span className="ml-2 badge bg-blue-800/40 text-blue-200">
                納品済み
              </span>
            )}
          </div>
        </div>
      );
    },
    costForScene: (sceneIdx) => {
      const scene = sp.scenes[sceneIdx];
      if (!scene) return null;
      return klingSceneCost(scene.duration, klingRate);
    },
    contextForScene: (sceneIdx): SceneContext => ({
      newAudioDuration: sp.scenes[sceneIdx]?.duration,
    }),
    renderSceneExtras: (sceneIdx) => {
      const scene = sp.scenes[sceneIdx];
      if (!scene) return null;
      return (
        <div className="space-y-2 mb-2">
          <ComposedPromptPreview
            ts={ts}
            sceneIdx={sceneIdx}
            field="animation_prompt"
            version={ctx.detail.progress.stages.kling.regen_count}
          />
          <SceneTtsRow lines={scene.lines ?? []} />
        </div>
      );
    },
  };

  return (
    <CacheDecisionFlow<KlingCandidateMeta>
      ts={ts}
      sceneCount={sceneCount}
      api={api.klingCache}
      presenter={presenter}
      assetLabel="動画"
      onGenerated={ctx.reload}
    />
  );
}

// ───────────── 生成済み (= 結果表示 + per-scene 再生成) ─────────────

function KlingResultsView() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const { rate: klingRate } = useCostMedianRate(
    "kling",
    ctx.serverConfig.cost_models.kling,
  );
  const totalCost = sp.scenes.reduce<number | null>((a, s) => {
    const c = klingSceneCost(s.duration, klingRate);
    if (c == null) return a;
    return (a ?? 0) + c;
  }, null);
  return (
    <div>
      <BulkKlingRegenBar totalCost={totalCost} />
      <div className="flex flex-col gap-3">
        {sp.scenes.map((scene, i) => (
          <KlingResultCard
            key={scene._uid ?? i}
            scene={scene}
            sIdx={i}
            rate={klingRate}
          />
        ))}
      </div>
    </div>
  );
}

// BulkKlingRegenBar は ./BulkKlingRegenBar.tsx に移管済 (= §3.1.3)。
// klingBilledDuration / klingSceneCost / formatKlingCost は ./kling-utils.ts。
// KlingResultCard は ./KlingResultCard.tsx に移管済。

