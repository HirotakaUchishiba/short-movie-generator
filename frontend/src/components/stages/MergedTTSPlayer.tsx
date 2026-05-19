// StageTTS.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// 全シーン TTS (one-shot で生成された merged mp3) を <audio> で再生する。
// regen_count を key と URL クエリに含めて、再生成のたびにブラウザ cache を
// 回避し最新の音声を再ロードする。

import { ttsMergedAssetUrl } from "../../api";
import { useShellCtx } from "../StageGate";

export function MergedTTSPlayer() {
  const ctx = useShellCtx();
  const v = ctx.detail.progress.stages.tts.regen_count;
  return (
    <div className="card border-emerald-700/40 bg-slate-800/60 mt-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="font-semibold">全シーンTTS (one-shot)</h3>
          <p className="text-xs text-slate-400 mt-1">
            screenplay全体を1 API call
            で生成した結果。シーン間が連続したプロソディで再生されます。
          </p>
        </div>
        <span className="text-xs text-slate-500">バージョン: regen×{v}</span>
      </div>
      <audio
        key={`merged-tts-${v}`}
        src={ttsMergedAssetUrl(ctx.detail.timestamp, v)}
        controls
        preload="metadata"
        className="w-full mt-3 h-10"
      />
    </div>
  );
}
