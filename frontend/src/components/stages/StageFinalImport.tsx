import { useEffect, useState, useCallback } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { api, finalVersionAssetUrl } from "../../api";
import type { FinalVersion } from "../../types";

export default function StageFinalImport() {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const overlayApproved = !!ctx.detail.progress.stages.overlay.approved_at;

  const [versions, setVersions] = useState<FinalVersion[]>([]);
  const [error, setError] = useState<string | null>(null);

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
    // auto_loop が背景で取込を実行する可能性があるので 5 秒ごとに再ロード
    const id = setInterval(reload, 5000);
    return () => clearInterval(id);
  }, [reload]);

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
      title="取り込み"
      description="auto_loop が pipeline raw を取り込み canonical 化する。複数の final が存在する場合はここで canonical を切替えて公開対象を選択する。"
    >
      {!overlayApproved ? (
        <div className="card text-center text-slate-400">
          まだ 字幕 が承認されていません。pipeline raw
          が出力されてから取り込みます。
        </div>
      ) : (
        <>
          {error && (
            <div className="rounded border border-rose-700 bg-rose-900/40 p-3 text-sm mb-4">
              <div className="flex justify-between">
                <span>{error}</span>
                <button onClick={() => setError(null)}>✕</button>
              </div>
            </div>
          )}

          {!canonical && versions.length === 0 && (
            <div className="card text-center text-slate-400">
              まだ取り込まれた final バージョンがありません。auto_loop による
              取込を待つか、CLI から `python3 main.py --resume {ts}{" "}
              --list-finals` で確認してください。
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
