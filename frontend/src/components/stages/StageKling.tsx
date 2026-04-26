import { useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { klingAssetUrl, sceneTrimAssetUrl, api } from "../../api";
import type { Scene } from "../../types";

export default function StageKling() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;

  return (
    <StageGate
      stage="kling"
      title="Stage 4: Kling動画"
      description="背景を動かしたシーンクリップを確認。最高額のステージなので慎重に。"
      needsRunFirst
    >
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        {sp.scenes.map((scene, i) => (
          <KlingCard key={i} scene={scene} sIdx={i} />
        ))}
      </div>
    </StageGate>
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

  const COST_PER_SEC = 0.084;
  const cost = (scene.duration <= 5 ? 5 : 10) * COST_PER_SEC;

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
          シーン{sIdx + 1} · {scene.time} {scene.label} · {scene.duration}s
        </span>
        <button
          className="btn-ghost text-xs"
          onClick={() => setShowRaw((v) => !v)}
          title="生クリップ ↔ trim後を切替"
        >
          {showRaw ? "trim後" : "生raw"}
        </button>
      </div>
      <p className="text-xs text-slate-300 line-clamp-3 mb-2" title={prompt}>
        {prompt}
      </p>
      {error && <div className="text-rose-400 text-xs mb-2">{error}</div>}
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
