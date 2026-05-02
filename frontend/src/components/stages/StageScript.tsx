import { useEffect, useState } from "react";
import { useShellCtx } from "../StageGate";
import StageGate from "../StageGate";
import { api } from "../../api";
import type { CharacterDef, Line, Scene } from "../../types";

const EMOTION_COLOR: Record<string, string> = {
  驚き: "bg-amber-700/40 text-amber-100",
  喜び: "bg-emerald-700/40 text-emerald-100",
  焦り: "bg-rose-700/40 text-rose-100",
  落胆: "bg-slate-600/40 text-slate-200",
  中立: "bg-slate-700/40 text-slate-200",
  満足: "bg-teal-700/40 text-teal-100",
  困惑: "bg-violet-700/40 text-violet-100",
  怒り: "bg-red-700/40 text-red-100",
  恥ずかしさ: "bg-pink-700/40 text-pink-100",
};

function CharactersChip({ characters }: { characters?: CharacterDef[] }) {
  if (!characters || characters.length === 0) {
    return (
      <span className="text-xs text-slate-500">
        登場人物未指定 (主人公シングル想定)
      </span>
    );
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {characters.map((c, i) => (
        <span
          key={i}
          className="text-xs bg-slate-700/60 text-slate-100 px-2 py-0.5 rounded"
        >
          <span className="font-medium">{c.name}</span>
          {c.role && <span className="text-slate-400 ml-1">({c.role})</span>}
        </span>
      ))}
    </div>
  );
}

function LineRow({ line, idx }: { line: Line; idx: number }) {
  const start = typeof line.start === "number" ? line.start : null;
  const end = typeof line.end === "number" ? line.end : null;
  const emotionClass =
    (line.emotion && EMOTION_COLOR[line.emotion]) ||
    "bg-slate-700/40 text-slate-200";
  return (
    <li className="border-l-2 border-emerald-600/40 pl-3 py-2">
      <div className="flex items-center gap-2 text-xs text-slate-400 mb-1 flex-wrap">
        <span className="font-mono">#{idx + 1}</span>
        {start !== null && (
          <span className="font-mono">
            {start.toFixed(1)}s{end !== null && ` ─ ${end.toFixed(1)}s`}
          </span>
        )}
        {line.emotion && (
          <span className={`px-2 py-0.5 rounded ${emotionClass}`}>
            {line.emotion}
          </span>
        )}
        {line.emotion_intensity && (
          <span className="text-slate-500">({line.emotion_intensity})</span>
        )}
        {line.rate && (
          <span className="text-slate-500 font-mono">rate {line.rate}</span>
        )}
      </div>
      <div className="text-base font-medium leading-relaxed">
        {line.speaker && (
          <span className="text-emerald-300 mr-2">【{line.speaker}】</span>
        )}
        {line.text}
      </div>
      {line.delivery && (
        <div className="text-xs text-slate-400 mt-1 italic">
          → 話し方: {line.delivery}
        </div>
      )}
      {line.audio_tags && line.audio_tags.length > 0 && (
        <div className="text-xs text-slate-500 mt-1">
          audio_tags: {line.audio_tags.join(", ")}
        </div>
      )}
      {line.subtitles && line.subtitles.length > 0 && (
        <div className="text-xs text-slate-500 mt-1">
          字幕チャンク {line.subtitles.length} 個 (手動指定)
        </div>
      )}
      {line.acoustic && (
        <div className="text-xs text-slate-600 font-mono mt-1">
          {line.acoustic.pitch_trend && `pitch ${line.acoustic.pitch_trend} `}
          {line.acoustic.rms_peak != null &&
            `rms ${line.acoustic.rms_peak.toFixed(2)} `}
          {line.acoustic.wpm != null && `wpm ${Math.round(line.acoustic.wpm)}`}
        </div>
      )}
    </li>
  );
}

function SceneCard({ scene, idx }: { scene: Scene; idx: number }) {
  const [open, setOpen] = useState(true);
  const lines = scene.lines ?? [];
  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3 mb-2">
        <button className="text-left flex-1" onClick={() => setOpen((v) => !v)}>
          <div className="flex items-baseline gap-3 flex-wrap">
            <span className="text-lg font-bold text-emerald-300">
              シーン {idx + 1}
            </span>
            {scene.label && (
              <span className="text-slate-200 font-medium">{scene.label}</span>
            )}
            <span className="text-xs text-slate-500 font-mono">
              {scene.duration}s · {lines.length} セリフ
            </span>
            {scene.lipsync === false && (
              <span className="text-xs text-slate-500">lipsync OFF</span>
            )}
          </div>
        </button>
        <button
          className="btn-ghost text-xs shrink-0"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "▼ 閉じる" : "▶ 開く"}
        </button>
      </div>

      <div className="mb-2">
        <CharactersChip characters={scene.characters} />
      </div>

      {open && (
        <div className="space-y-3 mt-3">
          {lines.length === 0 ? (
            <div className="text-sm text-slate-500 italic">セリフなし</div>
          ) : (
            <ul className="space-y-1">
              {lines.map((line, lIdx) => (
                <LineRow key={lIdx} line={line} idx={lIdx} />
              ))}
            </ul>
          )}

          {scene.background_prompt && (
            <details className="text-xs">
              <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
                背景プロンプト (Imagen)
              </summary>
              <div className="mt-1 pl-3 text-slate-300 whitespace-pre-wrap">
                {scene.background_prompt}
              </div>
            </details>
          )}
          {scene.animation_prompt && (
            <details className="text-xs">
              <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
                動作プロンプト (Kling)
              </summary>
              <div className="mt-1 pl-3 text-slate-300 whitespace-pre-wrap font-mono">
                {scene.animation_prompt}
              </div>
            </details>
          )}
          {scene.location_ref && (
            <div className="text-xs text-slate-500">
              location: <span className="font-mono">{scene.location_ref}</span>
            </div>
          )}
          {scene.wardrobe?.identifier && (
            <div className="text-xs text-slate-500">
              wardrobe:{" "}
              <span className="font-mono">{scene.wardrobe.identifier}</span>
            </div>
          )}
          {scene.character_refs && scene.character_refs.length > 0 && (
            <div className="text-xs text-slate-500">
              キャラ参照画像:{" "}
              <span className="font-mono">
                {scene.character_refs.join(", ")}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function StageScript() {
  const ctx = useShellCtx();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [allOpen, setAllOpen] = useState(true);

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
  const totalLines = sp.scenes.reduce((a, s) => a + (s.lines?.length ?? 0), 0);

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
          <div className="label mt-3">scenes / lines</div>
          <div className="text-sm">
            {sp.scenes.length} シーン · {totalLines} セリフ
          </div>
          <div className="label mt-3">total duration</div>
          <div className="text-sm">
            {sp.scenes.reduce((a, s) => a + s.duration, 0).toFixed(1)} 秒
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold">シーン詳細</h3>
        <button
          className="btn-ghost text-xs"
          onClick={() => setAllOpen((v) => !v)}
          key={String(allOpen)}
        >
          {allOpen ? "全て閉じる" : "全て開く"}
        </button>
      </div>
      <div className="space-y-3 mb-6">
        {sp.scenes.map((s, i) => (
          <SceneCard key={`${i}-${allOpen}`} scene={s} idx={i} />
        ))}
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
