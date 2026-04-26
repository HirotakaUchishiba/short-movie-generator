import { useState } from "react";
import StageGate, { useShellCtx } from "../StageGate";
import { overlayAssetUrl, api } from "../../api";
import type { Screenplay, Line } from "../../types";

export default function StageOverlay() {
  const ctx = useShellCtx();
  const sp = ctx.detail.screenplay;
  const [draft, setDraft] = useState<Screenplay>(
    JSON.parse(JSON.stringify(sp)),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateLine = (sIdx: number, lIdx: number, patch: Partial<Line>) => {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d)) as Screenplay;
      const line = next.scenes[sIdx].lines![lIdx];
      next.scenes[sIdx].lines![lIdx] = { ...line, ...patch };
      return next;
    });
  };

  const onApply = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.saveScreenplay(ctx.detail.timestamp, draft);
      await ctx.reload();
      await ctx.regen({ stage: "overlay" });
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const sceneOffsets: number[] = [];
  let acc = 0;
  for (const s of sp.scenes) {
    sceneOffsets.push(acc);
    acc += s.duration;
  }

  return (
    <StageGate
      stage="overlay"
      title="Stage 7: 字幕オーバーレイ"
      description="シーン連結後に字幕を焼き込んだ動画を確認。字幕テキスト・タイミングを編集できます。"
      needsRunFirst
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <div className="aspect-[9/16] bg-slate-950 overflow-hidden rounded mb-3 max-w-md mx-auto">
            <video
              key={ctx.detail.progress.stages.overlay.regen_count}
              src={overlayAssetUrl(
                ctx.detail.timestamp,
                ctx.detail.progress.stages.overlay.regen_count,
              )}
              controls
              playsInline
              className="w-full h-full"
            />
          </div>
        </div>
        <div className="card">
          <div className="flex justify-between items-center mb-3">
            <h3 className="font-semibold">字幕一覧</h3>
            <button className="btn-primary" disabled={saving} onClick={onApply}>
              {saving ? "焼き直し中..." : "保存して焼き直し"}
            </button>
          </div>
          {error && <div className="text-rose-400 text-xs mb-2">{error}</div>}
          <div className="max-h-[600px] overflow-auto">
            <table className="w-full text-xs">
              <thead className="text-slate-400 sticky top-0 bg-slate-800">
                <tr>
                  <th className="text-left p-1">S</th>
                  <th className="text-left p-1">絶対 開始</th>
                  <th className="text-left p-1">start</th>
                  <th className="text-left p-1">end</th>
                  <th className="text-left p-1">text</th>
                </tr>
              </thead>
              <tbody>
                {draft.scenes.flatMap((scene, sIdx) =>
                  (scene.lines ?? []).map((line, lIdx) => (
                    <tr
                      key={`${sIdx}-${lIdx}`}
                      className="border-t border-slate-700"
                    >
                      <td className="p-1 text-slate-500">{sIdx + 1}</td>
                      <td className="p-1 text-slate-500">
                        {(sceneOffsets[sIdx] + line.start).toFixed(2)}s
                      </td>
                      <td className="p-1">
                        <input
                          type="number"
                          step="0.1"
                          className="input text-xs py-1"
                          value={line.start}
                          onChange={(e) =>
                            updateLine(sIdx, lIdx, {
                              start: Number(e.target.value),
                            })
                          }
                        />
                      </td>
                      <td className="p-1">
                        <input
                          type="number"
                          step="0.1"
                          className="input text-xs py-1"
                          value={line.end ?? ""}
                          onChange={(e) =>
                            updateLine(sIdx, lIdx, {
                              end:
                                e.target.value === ""
                                  ? undefined
                                  : Number(e.target.value),
                            })
                          }
                        />
                      </td>
                      <td className="p-1">
                        <input
                          className="input text-xs py-1"
                          value={line.text}
                          onChange={(e) =>
                            updateLine(sIdx, lIdx, { text: e.target.value })
                          }
                        />
                      </td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </StageGate>
  );
}
