// Stage 4: Kling 動画。
// 未生成: CacheDecisionFlow (= scan / 判断 / 残りを生成)。
// 生成済み: 各シーンの動画 + per-scene 再生成。
import { useEffect, useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api, klingAssetUrl, sceneTrimAssetUrl } from "../../api";
import ComposedPromptPreview from "../ComposedPromptPreview";
import SceneTtsRow from "../SceneTtsRow";
import SceneFieldEditor from "../SceneFieldEditor";
import CacheDecisionFlow from "../cache/CacheDecisionFlow";
import type { CachePresenter, SceneContext } from "../cache/types";
import type {
  KlingCandidateMeta,
  KlingSceneDecision,
  Scene,
} from "../../types";

const KLING_COST_PER_SEC = 0.084;
// config.KLING_DURATION_TOLERANCE_RATIO と同期。5.01s で即 10s 切替を避けるため
// 5s 上限を 5.0 * 1.2 = 6.0s まで吸収する (超過分は slow_mo)。
const KLING_DURATION_TOLERANCE_RATIO = 1.2;

function klingSceneCost(durationSec: number): number {
  const fiveSecMax = 5 * KLING_DURATION_TOLERANCE_RATIO;
  return (durationSec <= fiveSecMax ? 5 : 10) * KLING_COST_PER_SEC;
}

export default function StageKling() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const generated = !!ctx.detail.progress.stages.kling.generated_at;

  return (
    <StageGate
      stage="kling"
      title="Stage 4: Kling動画"
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
      return scene ? klingSceneCost(scene.duration) : 0;
    },
    contextForScene: (sceneIdx): SceneContext => ({
      newAudioDuration: sp.scenes[sceneIdx]?.duration,
    }),
    renderSceneExtras: (sceneIdx) => {
      const scene = sp.scenes[sceneIdx];
      if (!scene) return null;
      return (
        <div className="space-y-2 mb-2">
          <SceneFieldEditor
            scene={scene}
            sIdx={sceneIdx}
            fields={["animation_style", "camera_distance"]}
          />
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
  const totalCost = sp.scenes.reduce(
    (a, s) => a + klingSceneCost(s.duration),
    0,
  );
  return (
    <div>
      <BulkKlingRegenBar totalCost={totalCost} />
      <div className="flex flex-col gap-3">
        {sp.scenes.map((scene, i) => (
          <KlingResultCard key={i} scene={scene} sIdx={i} />
        ))}
      </div>
    </div>
  );
}

function BulkKlingRegenBar({ totalCost }: { totalCost: number }) {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const [confirming, setConfirming] = useState(false);
  const running = ctx.jobStatus?.status === "running";

  const onResetToScan = async () => {
    setConfirming(false);
    try {
      await api.klingCache.decisionsBulk(ts, "all-fresh");
      await ctx.regen({ stage: "kling" });
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="card border-rose-700/40 bg-rose-900/10 mb-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">全シーン Kling動画を一括再生成</h3>
          <p className="text-xs text-slate-400 mt-1">
            cache 採用も新規生成も含め、全シーンを破棄して新規生成します。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">
            合計コスト:{" "}
            <span className="text-rose-300 font-mono">
              ${totalCost.toFixed(2)}
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
                本当に ${totalCost.toFixed(2)} 使う
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function KlingResultCard({ scene, sIdx }: { scene: Scene; sIdx: number }) {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const [showRaw, setShowRaw] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<KlingSceneDecision | null>(null);
  const [showAlt, setShowAlt] = useState(false);

  useEffect(() => {
    api.klingCache
      .decisions(ts)
      .then((s) => setDecision(s.scene_decisions[String(sIdx)] ?? null))
      .catch(() => {});
  }, [ts, sIdx, ctx.detail.progress.stages.kling.regen_count]);

  const cost = klingSceneCost(scene.duration);
  const isCached = decision?.decision === "cache";
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
          <span>
            シーン{sIdx + 1} · {scene.duration}s{" "}
            {isCached && (
              <span className="badge bg-emerald-700 text-emerald-100 ml-2">
                ♻️ cached
              </span>
            )}
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
        <SceneFieldEditor
          scene={scene}
          sIdx={sIdx}
          fields={["animation_style", "camera_distance"]}
        />
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
        <div className="flex justify-end gap-2">
          {!confirming ? (
            <button
              className="btn-secondary text-xs"
              onClick={() => setConfirming(true)}
            >
              再生成 (${cost.toFixed(2)})
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
                {saving ? "実行中..." : `本当に ${cost.toFixed(2)} 使う`}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
