import { useOutletContext } from "react-router-dom";
import { reelsAssetUrl } from "../../asset-urls";
import type {
  JobStatus,
  ProjectDetail,
  Screenplay,
  ServerConfig,
  StageName,
} from "../../types";

type Ctx = {
  detail: ProjectDetail & { screenplay: Screenplay; screenplay_name: string };
  serverConfig: ServerConfig;
  reload: () => Promise<void>;
  reloadConfig: () => Promise<void>;
  approveCurrent: (stage: StageName) => Promise<void>;
  runNext: () => Promise<void>;
  regen: unknown;
  jobStatus: JobStatus | null;
};

export default function StageDownload() {
  const ctx = useOutletContext<Ctx>();
  const ts = ctx.detail.timestamp;
  // overlay stage で書き出された pipeline raw (= 完成動画)。preview_server の
  // /asset/<ts>/reels route で配信される (= 無ければ overlaid.mp4 にフォールバック)。
  const filename = `reels_${ts}.mp4`;
  const url = reelsAssetUrl(ts);
  const overlayApproved = !!ctx.detail.progress.stages.overlay?.approved_at;

  if (!overlayApproved) {
    return (
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">完成</h2>
        <p className="text-sm text-slate-400">
          字幕オーバーレイを承認するとここに完成動画が表示されます。
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">完成 — ダウンロード</h2>
      <p className="text-sm text-slate-400">
        字幕オーバーレイ済みの最終動画です。再生して確認のうえダウンロードしてください。
      </p>
      <video
        key={url}
        src={url}
        controls
        className="w-full max-w-md rounded border border-slate-700"
      />
      <div>
        <a
          href={url}
          download={filename}
          className="inline-block rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
        >
          ⬇ {filename} をダウンロード
        </a>
      </div>
    </section>
  );
}
