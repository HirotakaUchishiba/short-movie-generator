import { useState, type CSSProperties } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { bgAssetUrl, api } from "../../api";
import type { Scene } from "../../types";

export default function StageBG() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;

  return (
    <StageGate
      stage="bg"
      title="Stage 3: 背景画像"
      description="各シーンの背景画像を確認。プロンプトを修正して個別に再生成できます。"
      needsRunFirst
    >
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        {sp.scenes.map((scene, i) => (
          <BGCard key={i} scene={scene} sIdx={i} />
        ))}
      </div>
    </StageGate>
  );
}

function BGCard({ scene, sIdx }: { scene: Scene; sIdx: number }) {
  const ctx = useShellCtx();
  const cfg = ctx.serverConfig;
  const [editing, setEditing] = useState(false);
  const [prompt, setPrompt] = useState(scene.background_prompt ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const subBoxStyle: CSSProperties = {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: `${(cfg.subtitle_y_from_bottom / cfg.video_height) * 100}%`,
    height: "12%",
    background: "rgba(244, 63, 94, 0.25)",
    borderTop: "1px dashed rgba(244, 63, 94, 0.6)",
    borderBottom: "1px dashed rgba(244, 63, 94, 0.6)",
    pointerEvents: "none",
  };

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
        <div style={subBoxStyle} title="字幕表示領域 (赤=被写体侵入注意)" />
        <div className="absolute top-1 left-2 text-xs bg-black/60 px-1.5 py-0.5 rounded">
          {scene.time} {scene.label}
        </div>
      </div>
      <div className="space-y-2">
        <div className="text-xs text-slate-400">
          duration {scene.duration}s · refs:{" "}
          {(scene.character_refs ?? scene.characters?.map((c) => c.ref))
            ?.filter(Boolean)
            .join(", ") || "-"}
        </div>
        {!editing ? (
          <>
            <p className="text-xs text-slate-300 line-clamp-3" title={prompt}>
              {prompt}
            </p>
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
