import { useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { bgAssetUrl, api } from "../../api";
import ComposedPromptPreview from "../ComposedPromptPreview";
import EmotionCueOverridePanel from "../EmotionCueOverridePanel";
import ScopedAugmentationsPanel from "../ScopedAugmentationsPanel";
import SceneTtsRow from "../SceneTtsRow";
import type { Scene } from "../../types";

// Imagen 4 Standard 概算 (1024x1024 4:3): $0.04/画像
const IMAGEN_COST_PER_IMAGE = 0.04;

export default function StageBG() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const totalCost = sp.scenes.length * IMAGEN_COST_PER_IMAGE;

  return (
    <StageGate
      stage="bg"
      title="Stage 3: 背景画像"
      description="Imagen で生成された各シーンの背景画像を確認。lines[].emotion から導出される EMOTION_VISUAL_CUES と Stage 2 のTTS音響特徴 (audio_dynamics) が自動でプロンプトに注入されます。背景プロンプトのみ編集可。"
      needsRunFirst
    >
      <BulkBGRegenBar totalCost={totalCost} sceneCount={sp.scenes.length} />
      <ScopedAugmentationsPanel />
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        {sp.scenes.map((scene, i) => (
          <BGCard key={i} scene={scene} sIdx={i} />
        ))}
      </div>
    </StageGate>
  );
}

function BulkBGRegenBar({
  totalCost,
  sceneCount,
}: {
  totalCost: number;
  sceneCount: number;
}) {
  const ctx = useShellCtx();
  const [confirming, setConfirming] = useState(false);
  const running = ctx.jobStatus?.status === "running";

  const onClick = async () => {
    setConfirming(false);
    // scene_idx 未指定 → backend が全シーン一括再生成
    await ctx.regen({ stage: "bg" });
  };

  return (
    <div className="card border-amber-700/40 bg-amber-900/10 mb-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">全シーン背景を一括再生成</h3>
          <p className="text-xs text-slate-400 mt-1">
            合成後 prompt (emotion + TTS audio dynamics 反映済み) で
            すべてのシーンの背景画像を順次再生成します。
            台本やプロンプトを更新したあと最新状態に揃えるのに使います。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">
            {sceneCount}枚 ・合計コスト{" "}
            <span className="text-amber-300 font-mono">
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
                onClick={onClick}
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

function BGCard({ scene, sIdx }: { scene: Scene; sIdx: number }) {
  const ctx = useShellCtx();
  const [editing, setEditing] = useState(false);
  const [prompt, setPrompt] = useState(scene.background_prompt ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = JSON.parse(JSON.stringify(ctx.detail.screenplay));
      updated.scenes[sIdx].background_prompt = prompt;
      await api.saveScreenplay(ctx.detail.timestamp, updated);
      await ctx.reload();
      await ctx.regen({ stage: "bg", scene_idx: sIdx });
      setEditing(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card">
      <div className="relative aspect-[9/16] bg-slate-950 overflow-hidden rounded mb-3">
        <img
          key={ctx.detail.progress.stages.bg.regen_count}
          src={bgAssetUrl(
            ctx.detail.timestamp,
            sIdx,
            ctx.detail.progress.stages.bg.regen_count,
          )}
          alt={`scene ${sIdx + 1}`}
          className="w-full h-full object-cover"
          loading="lazy"
        />
        <div className="absolute top-1 left-2 text-xs bg-black/60 px-1.5 py-0.5 rounded">
          シーン{sIdx + 1}
        </div>
      </div>
      <div className="space-y-2">
        <div className="text-xs text-slate-400">
          duration {scene.duration}s · refs:{" "}
          {(scene.character_refs ?? scene.characters?.map((c) => c.ref))
            ?.filter(Boolean)
            .join(", ") || "-"}
        </div>
        <SceneTtsRow lines={scene.lines ?? []} />
        {!editing ? (
          <>
            <p className="text-xs text-slate-300 line-clamp-3" title={prompt}>
              {prompt}
            </p>
            <ComposedPromptPreview
              ts={ctx.detail.timestamp}
              sceneIdx={sIdx}
              field="background_prompt"
              version={ctx.detail.progress.stages.bg.regen_count}
            />
            <EmotionCueOverridePanel scene={scene} sIdx={sIdx} />
            <div className="flex justify-end gap-2">
              <button
                className="btn-ghost text-xs"
                onClick={() => setEditing(true)}
              >
                編集
              </button>
              <button
                className="btn-secondary text-xs"
                onClick={() => ctx.regen({ stage: "bg", scene_idx: sIdx })}
              >
                再生成
              </button>
            </div>
          </>
        ) : (
          <div className="space-y-2">
            <textarea
              className="input text-xs h-32 font-mono"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
            {error && <div className="text-rose-400 text-xs">{error}</div>}
            <div className="flex justify-end gap-2">
              <button
                className="btn-ghost text-xs"
                onClick={() => setEditing(false)}
              >
                キャンセル
              </button>
              <button
                className="btn-primary text-xs"
                disabled={saving}
                onClick={onSave}
              >
                {saving ? "保存+再生成中..." : "保存して再生成"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
