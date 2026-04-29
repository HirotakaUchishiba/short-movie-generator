import { useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import {
  sceneAssetUrl,
  sceneAudioAssetUrl,
  sceneTrimAssetUrl,
} from "../../api";
import type { Scene, Line } from "../../types";

export default function StageScene() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;

  return (
    <StageGate
      stage="scene"
      title="Stage 5+6: シーン動画 (音声+リップシンク)"
      description="Stage 4 のKling動画 + Stage 2 のTTS音声を合成しリップシンクを適用します。TTSは Stage 2 で確定済みなのでここでは編集できません。"
      needsRunFirst
    >
      <BulkSceneRegenBar scenes={sp.scenes} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {sp.scenes.map((scene, i) => (
          <SceneVideoCard key={i} scene={scene} sIdx={i} />
        ))}
      </div>
    </StageGate>
  );
}

// fal.ai sync-lipsync は1秒$0.05程度の従量課金。
// シーン尺の合計から見積もる (lipsync 有効シーンのみ)。
const LIPSYNC_COST_PER_SEC = 0.05;

function BulkSceneRegenBar({ scenes }: { scenes: Scene[] }) {
  const ctx = useShellCtx();
  const [confirming, setConfirming] = useState(false);
  const running = ctx.jobStatus?.status === "running";

  const lipsyncSeconds = scenes.reduce((acc, s) => {
    const lipsyncOn = s.lipsync !== false && (s.lines?.length ?? 0) > 0;
    return acc + (lipsyncOn ? s.duration : 0);
  }, 0);
  const totalCost = lipsyncSeconds * LIPSYNC_COST_PER_SEC;

  const onClick = async () => {
    setConfirming(false);
    await ctx.regen({ stage: "scene" });
  };

  return (
    <div className="card border-amber-700/40 bg-amber-900/10 mb-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">全シーン動画を一括再合成</h3>
          <p className="text-xs text-slate-400 mt-1">
            Stage 4 の Kling動画 + Stage 2 の TTS音声を全シーン分再合成し
            リップシンクを適用します。
          </p>
          <p className="text-xs text-amber-300/80 mt-1">
            ⚠ リップシンク有効シーンは fal.ai sync-lipsync が再呼出しされ
            **課金が発生** します ($0.05/秒)。 lipsync を無効化したいシーンは
            screenplay の `lipsync: false` を設定してください。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">
            lipsync対象 {lipsyncSeconds.toFixed(1)}s ・ 合計{" "}
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
              全シーン一括再合成
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

function SceneVideoCard({ scene, sIdx }: { scene: Scene; sIdx: number }) {
  const ctx = useShellCtx();

  return (
    <div className="card">
      {(() => {
        const sceneV = ctx.detail.progress.stages.scene.regen_count;
        const klingV = ctx.detail.progress.stages.kling.regen_count;
        return (
          <div className="flex gap-4">
            <div className="aspect-[9/16] w-48 flex-shrink-0 bg-slate-950 overflow-hidden rounded">
              <video
                key={`scene-${sceneV}`}
                src={sceneAssetUrl(ctx.detail.timestamp, sIdx, sceneV)}
                controls
                playsInline
                className="w-full h-full object-cover"
              />
            </div>
            <div className="flex-1 space-y-2">
              <h3 className="font-semibold">
                シーン{sIdx + 1}{" "}
                <span className="font-normal text-slate-400 text-sm">
                  ({scene.duration}s)
                </span>
              </h3>
              <div className="text-xs text-slate-400">
                lipsync: {scene.lipsync !== false ? "ON" : "OFF"} · lines:{" "}
                {scene.lines?.length ?? 0}
              </div>
              <div className="space-y-1">
                <div className="text-xs text-slate-400">音声トラックのみ:</div>
                <audio
                  key={`audio-${sceneV}`}
                  src={sceneAudioAssetUrl(ctx.detail.timestamp, sIdx, sceneV)}
                  controls
                  preload="none"
                  className="h-7 w-full"
                />
                <div className="text-xs text-slate-400 mt-2">
                  trim動画 (音声なし):
                </div>
                <video
                  key={`trim-${klingV}`}
                  src={sceneTrimAssetUrl(ctx.detail.timestamp, sIdx, klingV)}
                  controls
                  muted
                  className="w-full max-h-32"
                />
              </div>
              <LineTimeline lines={scene.lines ?? []} />
              <div className="flex flex-wrap gap-2 pt-2">
                <button
                  className="btn-secondary text-xs"
                  onClick={() => ctx.regen({ stage: "scene", scene_idx: sIdx })}
                  title="このシーンのKling動画 + TTS音声を再合成 (リップシンクのみやり直し)"
                >
                  音声合成+リップシンク 再実行
                </button>
              </div>
              <p className="text-[10px] text-slate-500 pt-1">
                TTS音声を変えたい場合は Stage 2 へ戻る。Kling動画は Stage 4 へ。
              </p>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

function LineTimeline({ lines }: { lines: Line[] }) {
  if (!lines.length) return null;
  const maxEnd = Math.max(...lines.map((l) => (l.end ?? l.start) + 1));
  return (
    <div>
      <div className="text-xs text-slate-400 mt-2 mb-1">タイムライン:</div>
      <div className="relative h-6 bg-slate-900 rounded">
        {lines.map((line, i) => {
          const left = (line.start / maxEnd) * 100;
          const right = ((line.end ?? line.start + 1) / maxEnd) * 100;
          return (
            <div
              key={i}
              className="absolute top-1 h-4 bg-emerald-600/60 rounded text-[10px] px-1 truncate"
              style={{ left: `${left}%`, width: `${right - left}%` }}
              title={line.text}
            >
              {line.text}
            </div>
          );
        })}
      </div>
    </div>
  );
}
