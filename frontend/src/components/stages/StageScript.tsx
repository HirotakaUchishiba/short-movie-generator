import { useState, useEffect } from "react";
import { useShellCtx } from "../StageGate";
import StageGate from "../StageGate";
import { api } from "../../api";

export default function StageScript() {
  const ctx = useShellCtx();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setText(JSON.stringify(ctx.detail.screenplay, null, 2));
  }, [ctx.detail.screenplay]);

  const onSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const parsed = JSON.parse(text);
      await api.saveScreenplay(ctx.detail.timestamp, parsed);
      await ctx.reload();
      setEditing(false);
    } catch (e) {
      setSaveError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const sp = ctx.detail.screenplay;

  return (
    <StageGate
      stage="script"
      title="Stage 1: 台本"
      description="台本JSONの内容を確認します。OKを押すまで次のstageには進みません。"
    >
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card col-span-2">
          <div className="label">caption</div>
          <pre className="whitespace-pre-wrap text-sm">{sp.caption}</pre>
        </div>
        <div className="card">
          <div className="label">audio_mode</div>
          <div className="text-sm">{sp.audio_mode ?? "voiced"}</div>
          <div className="label mt-3">bgm_path</div>
          <div className="text-sm break-all">{sp.bgm_path ?? "(なし)"}</div>
          <div className="label mt-3">scenes</div>
          <div className="text-sm">{sp.scenes.length}本</div>
          <div className="label mt-3">total duration</div>
          <div className="text-sm">
            {sp.scenes.reduce((a, s) => a + s.duration, 0).toFixed(1)} 秒
          </div>
        </div>
      </div>

      <div className="card mb-6">
        <h3 className="font-semibold mb-3">シーン一覧</h3>
        <table className="w-full text-sm">
          <thead className="text-slate-400">
            <tr className="text-left">
              <th>#</th>
              <th>duration</th>
              <th>lines</th>
              <th>背景プロンプト (抜粋)</th>
            </tr>
          </thead>
          <tbody>
            {sp.scenes.map((s, i) => (
              <tr key={i} className="border-t border-slate-700">
                <td className="py-2">{i + 1}</td>
                <td>{s.duration}s</td>
                <td>{s.lines?.length ?? 0}</td>
                <td className="truncate max-w-md" title={s.background_prompt}>
                  {s.background_prompt?.slice(0, 60) ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-semibold">JSON 直接編集</h3>
          {!editing ? (
            <button className="btn-secondary" onClick={() => setEditing(true)}>
              編集
            </button>
          ) : (
            <div className="flex gap-2">
              <button
                className="btn-ghost"
                onClick={() => {
                  setEditing(false);
                  setText(JSON.stringify(ctx.detail.screenplay, null, 2));
                }}
              >
                キャンセル
              </button>
              <button
                className="btn-primary"
                disabled={saving}
                onClick={onSave}
              >
                {saving ? "保存中..." : "screenplays/に保存"}
              </button>
            </div>
          )}
        </div>
        {saveError && (
          <div className="mb-2 text-rose-400 text-sm whitespace-pre-wrap">
            {saveError}
          </div>
        )}
        {editing ? (
          <textarea
            className="input font-mono text-xs h-96"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        ) : (
          <pre className="text-xs font-mono overflow-auto max-h-96 bg-slate-900 p-3 rounded">
            {text}
          </pre>
        )}
      </div>
    </StageGate>
  );
}
