// StageBG.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 1 シーン分の BG 結果カード:
//   - 背景画像プレビュー
//   - bg_cache / clip_library hit バッジ
//   - 別 cache 候補の swap UI
//   - 再生成 / キャッシュ無視ボタン

import { useEffect, useState } from "react";

import { api, bgAssetUrl } from "../../api";
import { useClipLibraryStatus } from "../../hooks/useClipLibraryStatus";
import type { BgSceneDecision, Scene } from "../../types";
import BgCacheBadge from "../BgCacheBadge";
import ClipLibraryBadge from "../ClipLibraryBadge";
import ComposedPromptPreview from "../ComposedPromptPreview";
import SceneTtsRow from "../SceneTtsRow";
import { useShellCtx } from "../StageGate";

export function BGResultCard({ scene, sIdx }: { scene: Scene; sIdx: number }) {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const [decision, setDecision] = useState<BgSceneDecision | null>(null);
  const [showAlt, setShowAlt] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // UI 5: 各 scene が clip_library hit するか (= 設計の中核 cost 削減経路の透明性)
  const clipStatus = useClipLibraryStatus(
    ts,
    ctx.detail.progress.stages.bg.regen_count,
  );
  const sceneClipStatus =
    clipStatus.kind === "ready"
      ? clipStatus.data.scenes.find((s) => s.scene_idx === sIdx)
      : undefined;

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
            {(
              scene.identity?.character_refs ??
              scene.characters?.map((c) => c.ref)
            )
              ?.filter(Boolean)
              .join(", ") || "-"}
          </span>
          <BgCacheBadge sIdx={sIdx} />
          <ClipLibraryBadge
            status={sceneClipStatus}
            enabled={
              clipStatus.kind === "ready" ? clipStatus.data.enabled : undefined
            }
          />
          {isCached && (
            <span className="badge bg-emerald-700 text-emerald-100">
              ♻️ cache 採用済み
            </span>
          )}
        </div>
        <SceneTtsRow lines={scene.lines ?? []} />
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
