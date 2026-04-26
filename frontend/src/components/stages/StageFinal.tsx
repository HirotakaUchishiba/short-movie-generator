import StageGate, { useShellCtx } from "../StageGate";
import { finalAssetUrl } from "../../api";

export default function StageFinal() {
  const ctx = useShellCtx();
  const finalApproved = !!ctx.detail.progress.stages.final.approved_at;

  return (
    <StageGate
      stage="final"
      title="完成: 最終動画"
      description="BGM mixと最終出力配置・SNSキャプション生成を行った最終成果物。"
      needsRunFirst
    >
      {finalApproved ? (
        <div className="card">
          <div className="aspect-[9/16] bg-slate-950 overflow-hidden rounded mx-auto max-w-md">
            <video
              src={finalAssetUrl(ctx.detail.timestamp)}
              controls
              playsInline
              className="w-full h-full"
            />
          </div>
          <div className="mt-4 text-center text-sm text-slate-400">
            <p>output/reels_{ctx.detail.timestamp}.mp4</p>
            <p className="mt-2">
              SNS投稿キャプションは <code>post_captions/</code>{" "}
              に生成されています。
            </p>
          </div>
        </div>
      ) : (
        <div className="card text-center text-slate-400">
          まだ最終生成が走っていません。Stage 7を承認すると自動で実行されます。
        </div>
      )}
    </StageGate>
  );
}
