import { useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { klingAssetUrl, sceneTrimAssetUrl, api } from "../../api";
import ComposedPromptPreview from "../ComposedPromptPreview";
import EmotionCueOverridePanel from "../EmotionCueOverridePanel";
import SceneTtsRow from "../SceneTtsRow";
import AutoAnimationPromptPanel from "../AutoAnimationPromptPanel";
import type { Scene } from "../../types";

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
  const totalCost = sp.scenes.reduce(
    (a, s) => a + klingSceneCost(s.duration),
    0,
  );

  return (
    <StageGate
      stage="kling"
      title="Stage 4: Kling動画"
      description="Stage 3 の背景画像に Kling V3 でモーションを付与。lines[].emotion arc + Stage 2 のTTS音響特徴 (audio_dynamics) が自動で animation_prompt に注入されます。最高額のステージなので慎重に。"
      needsRunFirst
    >
      <BulkKlingRegenBar totalCost={totalCost} />
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        {sp.scenes.map((scene, i) => (
          <KlingCard key={i} scene={scene} sIdx={i} />
        ))}
      </div>
    </StageGate>
  );
}

function BulkKlingRegenBar({ totalCost }: { totalCost: number }) {
  const ctx = useShellCtx();
  const [confirming, setConfirming] = useState(false);
  const running = ctx.jobStatus?.status === "running";

  const onClick = async () => {
    setConfirming(false);
    // scene_idx 未指定 → backend が全シーン一括再生成
    await ctx.regen({ stage: "kling" });
  };

  return (
    <div className="card border-rose-700/40 bg-rose-900/10 mb-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">全シーン Kling動画を一括再生成</h3>
          <p className="text-xs text-slate-400 mt-1">
            合成後 prompt (emotion + TTS audio dynamics 反映済み) を使って
            すべてのシーンの Kling clip を順次再生成します。
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

function KlingCard({ scene, sIdx }: { scene: Scene; sIdx: number }) {
  const ctx = useShellCtx();
  const [editing, setEditing] = useState(false);
  const [prompt, setPrompt] = useState(scene.animation_prompt ?? "");
  const [showRaw, setShowRaw] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cost = klingSceneCost(scene.duration);

  const onSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = JSON.parse(JSON.stringify(ctx.detail.screenplay));
      updated.scenes[sIdx].animation_prompt = prompt;
      await api.saveScreenplay(ctx.detail.timestamp, updated);
      await ctx.reload();
      await ctx.regen({ stage: "kling", scene_idx: sIdx });
      setEditing(false);
      setConfirming(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

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

  return (
    <div className="card">
      <div className="aspect-[9/16] bg-slate-950 overflow-hidden rounded mb-2">
        <video
          key={`${showRaw ? "raw" : "trim"}-${ctx.detail.progress.stages.kling.regen_count}`}
          src={
            showRaw
              ? klingAssetUrl(
                  ctx.detail.timestamp,
                  sIdx,
                  ctx.detail.progress.stages.kling.regen_count,
                )
              : sceneTrimAssetUrl(
                  ctx.detail.timestamp,
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
      <div className="flex justify-between items-center text-xs text-slate-400 mb-2">
        <span>
          シーン{sIdx + 1} · {scene.duration}s
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
      <p
        className="text-xs text-slate-300 line-clamp-3 mb-2 mt-2"
        title={prompt}
      >
        {prompt}
      </p>
      <ComposedPromptPreview
        ts={ctx.detail.timestamp}
        sceneIdx={sIdx}
        field="animation_prompt"
        version={ctx.detail.progress.stages.kling.regen_count}
      />
      <AutoAnimationPromptPanel
        ts={ctx.detail.timestamp}
        sceneIdx={sIdx}
        onAdopted={() => {
          ctx.reload();
        }}
      />
      <EmotionCueOverridePanel scene={scene} sIdx={sIdx} />
      {error && <div className="text-rose-400 text-xs mb-2 mt-2">{error}</div>}
      {!editing ? (
        <div className="flex justify-end gap-2">
          <button
            className="btn-ghost text-xs"
            onClick={() => setEditing(true)}
          >
            編集
          </button>
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
      ) : (
        <div className="space-y-2">
          <textarea
            className="input text-xs h-32 font-mono"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
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
              {saving
                ? "保存+再生成中..."
                : `保存→再生成 ($${cost.toFixed(2)})`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
