// Stage 3: 背景画像。
// 未生成: CacheDecisionFlow (= scan / 判断 / 残りを生成)。
// 生成済み: 各シーンの BG 画像 + per-scene 再生成。
import { useEffect, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api, bgAssetUrl } from "../../api";
import ComposedPromptPreview from "../ComposedPromptPreview";
import SceneTtsRow from "../SceneTtsRow";
import BgCacheBadge from "../BgCacheBadge";
import ClipLibraryBadge from "../ClipLibraryBadge";
import CacheDecisionFlow from "../cache/CacheDecisionFlow";
import type { CachePresenter, SceneContext } from "../cache/types";
import type { BgCandidateMeta, BgSceneDecision, Scene } from "../../types";
import { useClipLibraryStatus } from "../../hooks/useClipLibraryStatus";
import { useCostMedianRate } from "../../useCostMedianRate";
import { BGResultCard } from "./BGResultCard";
import { BulkBGRegenBar } from "./BulkBGRegenBar";

export default function StageBG() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const generated = !!ctx.detail.progress.stages.bg.generated_at;

  return (
    <StageGate
      stage="bg"
      title="背景画像"
      description="cache スキャン → シーンごとに『キャッシュ採用 / 新規生成』を判断 → 残りを一括生成。Imagen で各シーンの背景画像を生成します。"
    >
      {generated ? (
        <BgResultsView />
      ) : (
        <BgDecisionFlow
          ts={ctx.detail.timestamp}
          sceneCount={sp.scenes.length}
        />
      )}
    </StageGate>
  );
}

// ───────────── 判断前 (= 自動 scan + per-scene 判断) ─────────────

function BgDecisionFlow({
  ts,
  sceneCount,
}: {
  ts: string;
  sceneCount: number;
}) {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const { rate: bgRate } = useCostMedianRate(
    "bg",
    ctx.serverConfig.cost_models.bg,
  );

  const presenter: CachePresenter<BgCandidateMeta> = {
    renderPreview: (key) => (
      <img
        src={api.bgCache.previewUrl(key)}
        alt={`bg cache preview ${key}`}
        className="w-full h-full object-cover"
        loading="lazy"
      />
    ),
    renderCandidateMeta: (meta) => (
      <div className="text-slate-400 space-y-0.5">
        <div>
          location:{" "}
          <span className="font-mono text-slate-300">
            {meta.location_ref ?? "-"}
          </span>{" "}
          / camera:{" "}
          <span className="font-mono text-slate-300">
            {meta.camera_distance ?? "-"}
          </span>{" "}
          / hits: {meta.hit_count ?? 0}
          {meta.quality?.final_render_completed && (
            <span className="ml-2 badge bg-blue-800/40 text-blue-200">
              納品済み
            </span>
          )}
        </div>
        {meta.character_refs && meta.character_refs.length > 0 && (
          <div className="text-slate-500">
            refs:{" "}
            <span className="font-mono">{meta.character_refs.join(", ")}</span>
          </div>
        )}
        {meta.background_prompt_resolved && (
          <div
            className="text-slate-500 truncate"
            title={meta.background_prompt_resolved}
          >
            元 prompt: {meta.background_prompt_resolved.slice(0, 80)}
            {meta.background_prompt_resolved.length > 80 ? "..." : ""}
          </div>
        )}
      </div>
    ),
    costForScene: (_sceneIdx) => bgRate?.usd_per_unit ?? null,
    contextForScene: (_sceneIdx): SceneContext => ({}),
    renderSceneExtras: (sceneIdx) => {
      const scene = sp.scenes[sceneIdx];
      if (!scene) return null;
      return (
        <div className="space-y-2 mb-2">
          <ComposedPromptPreview
            ts={ts}
            sceneIdx={sceneIdx}
            field="background_prompt"
            version={ctx.detail.progress.stages.bg.regen_count}
          />
        </div>
      );
    },
  };

  return (
    <CacheDecisionFlow<BgCandidateMeta>
      ts={ts}
      sceneCount={sceneCount}
      api={api.bgCache}
      presenter={presenter}
      assetLabel="画像"
      onGenerated={ctx.reload}
    />
  );
}

// ───────────── 生成済み (= 結果表示 + per-scene 再生成) ─────────────

function BgResultsView() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const { rate: bgRate } = useCostMedianRate(
    "bg",
    ctx.serverConfig.cost_models.bg,
  );
  const totalCost =
    bgRate?.usd_per_unit != null
      ? sp.scenes.length * bgRate.usd_per_unit
      : null;

  return (
    <div>
      <BulkBGRegenBar totalCost={totalCost} sceneCount={sp.scenes.length} />
      <div className="flex flex-col gap-3">
        {sp.scenes.map((scene, i) => (
          <BGResultCard key={scene._uid ?? i} scene={scene} sIdx={i} />
        ))}
      </div>
    </div>
  );
}

// BulkBGRegenBar は ./BulkBGRegenBar.tsx に移管済 (= §3.1.3)。
// formatBgCost は ./bg-utils.ts に移管済。

// BGResultCard は ./BGResultCard.tsx に移管済 (= §3.1.3)。
