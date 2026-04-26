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
      description="既に完成しているKling動画に、TTS音声とリップシンクが合成された状態を確認します。"
      needsRunFirst
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {sp.scenes.map((scene, i) => (
          <SceneVideoCard key={i} scene={scene} sIdx={i} />
        ))}
      </div>
    </StageGate>
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
                  {scene.time} {scene.label} ({scene.duration}s)
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
                >
                  音声合成+リップシンク 再実行
                </button>
                <button
                  className="btn-secondary text-xs"
                  onClick={() => ctx.regen({ stage: "tts", scene_idx: sIdx })}
                >
                  TTSから再生成
                </button>
              </div>
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
