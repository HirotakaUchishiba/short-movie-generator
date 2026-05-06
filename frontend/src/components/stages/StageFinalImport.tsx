import { useEffect, useState, useCallback, useRef } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api, finalVersionAssetUrl } from "../../api";
import type { FinalVersion } from "../../types";

const SCORE_WARN_THRESHOLD = 0.6;

export default function StageFinalImport() {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const overlayApproved = !!ctx.detail.progress.stages.overlay.approved_at;

  const [versions, setVersions] = useState<FinalVersion[]>([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [skipFingerprint, setSkipFingerprint] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    try {
      const r = await api.listFinals(ts);
      setVersions(r.final_versions);
    } catch (e) {
      setError(String(e));
    }
  }, [ts]);

  useEffect(() => {
    reload();
    // watchdog 経由の取込もあるので 5 秒ごとに再ロード
    const id = setInterval(reload, 5000);
    return () => clearInterval(id);
  }, [reload]);

  const handleUpload = async (file: File) => {
    setError(null);
    setUploading(true);
    setProgress(0);
    try {
      await api.uploadFinal(ts, file, {
        skipFingerprint,
        onProgress: (p) => setProgress(p),
      });
      await reload();
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
      setProgress(0);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (uploading) return;
    const file = e.dataTransfer.files?.[0];
    if (file) handleUpload(file);
  };

  const setCanonical = async (filename: string) => {
    setError(null);
    try {
      await api.setCanonicalFinal(ts, filename);
      // backend 側で final_import 承認 + publish 進捗がリセットされるので
      // shell 全体の progress を取り直して StageGate の表示を同期させる
      await reload();
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const remove = async (filename: string) => {
    if (!confirm(`削除しますか? ${filename}`)) return;
    try {
      await api.deleteFinal(ts, filename);
      await reload();
      await ctx.reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const canonical = versions.find((v) => v.is_canonical) || null;

  return (
    <StageGate
      stage="final_import"
      title="Stage 8: CapCut 出力の取り込み"
      description="CapCut 等で手動編集した最終動画を取り込み、analytics と公開フローの正本にする。temp/<TS>/final/ にファイルを置けば watchdog が自動検知。"
    >
      {!overlayApproved ? (
        <div className="card text-center text-slate-400">
          まだ Stage 7 (字幕焼き込み) が承認されていません。pipeline raw
          が出力されてから取り込みます。
        </div>
      ) : (
        <>
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            className={`card border-2 border-dashed border-slate-500 text-center py-10 mb-4 ${
              uploading ? "opacity-50" : ""
            }`}
          >
            <p className="text-lg mb-2">CapCut 書き出しを ここにドロップ</p>
            <p className="text-sm text-slate-400 mb-4">
              または{" "}
              <button
                className="underline text-emerald-400"
                onClick={() => inputRef.current?.click()}
                disabled={uploading}
              >
                ファイル選択
              </button>{" "}
              (.mp4 / .mov / .m4v)
            </p>
            <input
              ref={inputRef}
              type="file"
              accept=".mp4,.mov,.m4v,video/mp4,video/quicktime"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleUpload(f);
              }}
            />
            <label className="text-xs text-slate-400 inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={skipFingerprint}
                onChange={(e) => setSkipFingerprint(e.target.checked)}
              />
              音声指紋検証をスキップ (高速)
            </label>
            {uploading && (
              <div className="mt-4">
                <div className="bg-slate-700 h-2 rounded">
                  <div
                    className="bg-emerald-500 h-2 rounded transition-all"
                    style={{ width: `${progress * 100}%` }}
                  />
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  アップロード中... {Math.round(progress * 100)}%
                </p>
              </div>
            )}
          </div>

          {error && (
            <div className="rounded border border-rose-700 bg-rose-900/40 p-3 text-sm mb-4">
              <div className="flex justify-between">
                <span>{error}</span>
                <button onClick={() => setError(null)}>✕</button>
              </div>
            </div>
          )}

          {canonical &&
            canonical.audio_match_score !== null &&
            canonical.audio_match_score < SCORE_WARN_THRESHOLD && (
              <div className="rounded border border-amber-700 bg-amber-900/30 p-3 text-sm mb-4">
                ⚠ 音声指紋スコアが低い ({canonical.audio_match_score.toFixed(2)}
                ) — pipeline
                出力と一致しない可能性があります。動画を確認してから承認してください。
              </div>
            )}

          {canonical && (
            <div className="card mb-4">
              <h3 className="text-lg font-semibold mb-2">canonical version</h3>
              <div className="aspect-[9/16] bg-slate-950 overflow-hidden rounded mx-auto max-w-md">
                <video
                  src={finalVersionAssetUrl(ts, canonical.filename)}
                  controls
                  playsInline
                  className="w-full h-full"
                />
              </div>
              <div className="mt-2 text-xs text-slate-400 text-center">
                {canonical.filename} ·{" "}
                {(canonical.size_bytes / 1024 / 1024).toFixed(1)} MB
                {canonical.duration_sec
                  ? ` · ${canonical.duration_sec.toFixed(1)}s`
                  : ""}
                {canonical.audio_match_score !== null
                  ? ` · score ${canonical.audio_match_score.toFixed(2)}`
                  : ""}
              </div>
            </div>
          )}

          {versions.length > 0 && (
            <div className="card">
              <h3 className="text-lg font-semibold mb-2">
                取込済みバージョン ({versions.length})
              </h3>
              <table className="w-full text-sm">
                <thead className="text-slate-400 border-b border-slate-700">
                  <tr>
                    <th className="text-left py-2">ファイル</th>
                    <th className="text-left">取込</th>
                    <th className="text-right">size</th>
                    <th className="text-right">duration</th>
                    <th className="text-right">score</th>
                    <th className="text-center">source</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {versions.map((v) => (
                    <tr
                      key={v.filename}
                      className={v.is_canonical ? "bg-emerald-900/30" : ""}
                    >
                      <td className="py-2">
                        {v.is_canonical && (
                          <span className="text-emerald-400 mr-1">★</span>
                        )}
                        {v.filename}
                      </td>
                      <td>{v.imported_at}</td>
                      <td className="text-right">
                        {(v.size_bytes / 1024 / 1024).toFixed(1)} MB
                      </td>
                      <td className="text-right">
                        {v.duration_sec ? `${v.duration_sec.toFixed(1)}s` : "—"}
                      </td>
                      <td className="text-right">
                        {v.audio_match_score !== null
                          ? v.audio_match_score.toFixed(2)
                          : "—"}
                      </td>
                      <td className="text-center text-xs">{v.source}</td>
                      <td className="text-right">
                        {!v.is_canonical && (
                          <button
                            className="btn-secondary text-xs mr-2"
                            onClick={() => setCanonical(v.filename)}
                          >
                            canonical に
                          </button>
                        )}
                        <button
                          className="btn-secondary text-xs"
                          onClick={() => remove(v.filename)}
                        >
                          削除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </StageGate>
  );
}
