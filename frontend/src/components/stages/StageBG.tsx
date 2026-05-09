// Stage 3: 背景画像。
// 未生成: CacheDecisionFlow (= scan / 判断 / 残りを生成)。
// 生成済み: 各シーンの BG 画像 + per-scene 再生成。
import { useEffect, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api, bgAssetUrl } from "../../api";
import ComposedPromptPreview from "../ComposedPromptPreview";
import SceneTtsRow from "../SceneTtsRow";
import SceneFieldEditor from "../SceneFieldEditor";
import BgCacheBadge from "../BgCacheBadge";
import CacheDecisionFlow from "../cache/CacheDecisionFlow";
import type { CachePresenter, SceneContext } from "../cache/types";
import type { BgCandidateMeta, BgSceneDecision, Scene } from "../../types";
import { useCostMedianRate } from "../../useCostMedianRate";

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
          <SceneFieldEditor
            scene={scene}
            sIdx={sceneIdx}
            fields={["location_ref", "camera_distance"]}
          />
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

function _formatBgCost(usd: number | null): string {
  return usd == null ? "履歴不足" : `$${usd.toFixed(2)}`;
}

function BulkBGRegenBar({
  totalCost,
  sceneCount,
}: {
  totalCost: number | null;
  sceneCount: number;
}) {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const [confirming, setConfirming] = useState(false);
  const running = ctx.jobStatus?.status === "running";

  const onResetToScan = async () => {
    setConfirming(false);
    // 全シーンを fresh queue にして Stage 3 を再生成 → 結果は再 scan ベース。
    try {
      await api.bgCache.decisionsBulk(ts, "all-fresh");
      await ctx.regen({ stage: "bg" });
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="card border-amber-700/40 bg-amber-900/10 mb-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">全シーン背景を一括再生成</h3>
          <p className="text-xs text-slate-400 mt-1">
            cache 採用も新規生成も含め、全シーンを破棄して新規生成します。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">
            {sceneCount}枚 ・合計コスト{" "}
            <span className="text-amber-300 font-mono">
              {_formatBgCost(totalCost)}
            </span>
          </span>
          {!confirming ? (
            <button
              className="btn-secondary"
              disabled={running}
              onClick={() => setConfirming(true)}
            >
              全シーン一括再生成
            </button>
          ) : (
            <>
              <button
                className="btn-ghost"
                onClick={() => setConfirming(false)}
              >
                キャンセル
              </button>
              <button
                className="btn-danger"
                disabled={running}
                onClick={onResetToScan}
              >
                本当に {_formatBgCost(totalCost)} 使う
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function BGResultCard({ scene, sIdx }: { scene: Scene; sIdx: number }) {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const [decision, setDecision] = useState<BgSceneDecision | null>(null);
  const [showAlt, setShowAlt] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.bgCache
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
  }, [ts, sIdx, ctx.detail.progress.stages.bg.regen_count]);

  const isCached = decision?.decision === "cache";
  const altCandidates =
    (decision?.candidates ?? []).filter(
      (c) => c.key !== decision?.decided_key,
    ) ?? [];

  const onSwapToCache = async (key: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.bgCache.useCache(ts, sIdx, key);
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card flex flex-row gap-4 items-start">
      <div className="relative w-32 sm:w-36 aspect-[9/16] bg-slate-950 overflow-hidden rounded shrink-0">
        <img
          key={ctx.detail.progress.stages.bg.regen_count}
          src={bgAssetUrl(ts, sIdx, ctx.detail.progress.stages.bg.regen_count)}
          alt={`scene ${sIdx + 1}`}
          className="w-full h-full object-cover"
          loading="lazy"
        />
        <div className="absolute top-1 left-1 text-[10px] bg-black/60 px-1 py-0.5 rounded">
          #{sIdx + 1}
        </div>
      </div>
      <div className="flex-1 min-w-0 space-y-2">
        <div className="text-xs text-slate-400 flex items-center gap-2 flex-wrap">
          <span>
            duration {scene.duration}s · refs:{" "}
            {(scene.character_refs ?? scene.characters?.map((c) => c.ref))
              ?.filter(Boolean)
              .join(", ") || "-"}
          </span>
          <BgCacheBadge sIdx={sIdx} />
          {isCached && (
            <span className="badge bg-emerald-700 text-emerald-100">
              ♻️ cache 採用済み
            </span>
          )}
        </div>
        <SceneTtsRow lines={scene.lines ?? []} />
        <SceneFieldEditor
          scene={scene}
          sIdx={sIdx}
          fields={["location_ref", "camera_distance"]}
        />
        <ComposedPromptPreview
          ts={ts}
          sceneIdx={sIdx}
          field="background_prompt"
          version={ctx.detail.progress.stages.bg.regen_count}
        />
        {error && <div className="text-rose-400 text-xs">{error}</div>}
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
                    <img
                      src={api.bgCache.previewUrl(c.key)}
                      alt={c.key}
                      className="w-16 h-28 object-cover rounded"
                      loading="lazy"
                    />
                    <div className="flex-1 text-xs space-y-1">
                      <div>適合度 {Math.round(c.fitness * 100)}%</div>
                      <div className="text-slate-500">
                        location: {c.meta.location_ref ?? "-"} / hits:{" "}
                        {c.meta.hit_count ?? 0}
                      </div>
                      <button
                        className="btn-secondary text-xs"
                        disabled={busy}
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
        <div className="flex justify-end gap-2">
          <button
            className="btn-ghost text-xs"
            onClick={() =>
              ctx.regen({ stage: "bg", scene_idx: sIdx, force_no_cache: true })
            }
            title="cache を無視して Imagen API を必ず呼び出す"
          >
            キャッシュ無視
          </button>
          <button
            className="btn-secondary text-xs"
            onClick={() => ctx.regen({ stage: "bg", scene_idx: sIdx })}
          >
            再生成
          </button>
        </div>
      </div>
    </div>
  );
}
