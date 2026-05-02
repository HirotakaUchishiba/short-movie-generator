import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type {
  AnalyzeJobDetail,
  SceneOverride,
  Screenplay,
  VideoStyle,
} from "../types";

interface AbstractScene {
  duration: number;
  lines: { text?: string; emotion?: string; speaker?: string }[];
}

export default function StyleEditorPage() {
  const { job: jobId = "" } = useParams<{ job: string }>();
  const navigate = useNavigate();

  const [job, setJob] = useState<AnalyzeJobDetail | null>(null);
  const [abstract, setAbstract] = useState<{
    caption: string;
    scenes: AbstractScene[];
  } | null>(null);
  const [styles, setStyles] = useState<VideoStyle[]>([]);
  const [selectedStyle, setSelectedStyle] = useState<string>("");
  const [overrides, setOverrides] = useState<Record<number, SceneOverride>>({});
  const [composing, setComposing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [doneScreenplayPath, setDoneScreenplayPath] = useState<string | null>(
    null,
  );

  // ジョブと抽象台本と style 一覧を初期ロード
  useEffect(() => {
    if (!jobId) return;
    Promise.all([api.getAnalyzeJob(jobId), api.listStyles()])
      .then(async ([j, ls]) => {
        setJob(j);
        setStyles(ls.styles);
        if (ls.styles.length > 0) setSelectedStyle(ls.styles[0].name);
        // 抽象台本ファイルを fetch (絶対パスから basename を抽出して
        // /asset/ や別ルートに通す手段がないため、screenplay は ProjectDetail
        // ロード時のものを取得する代わりに、API 経由で簡易的に取得する。
        // ここでは job.screenplay_path をクライアントが直読みする手段がないため、
        // とりあえず caption と scenes 数だけ表示するのは job.phases から推定。
        // → 一旦 abstract は ProjectDetail ロードの代わりに合成プレビューで
        // やる方針に変えるが、最低限のシーン数を出すため scenes count を null
        // に。
        setAbstract(null);
      })
      .catch((e) => setError(String(e)));
  }, [jobId]);

  const selected = useMemo(
    () => styles.find((s) => s.name === selectedStyle) || null,
    [styles, selectedStyle],
  );

  const onCompose = async () => {
    if (!selectedStyle) return;
    setComposing(true);
    setError(null);
    try {
      const r = await api.composeScreenplay(
        jobId,
        selectedStyle,
        Object.keys(overrides).length > 0
          ? Object.fromEntries(
              Object.entries(overrides).map(([k, v]) => [String(k), v]),
            )
          : undefined,
      );
      setDoneScreenplayPath(r.screenplay_path);
    } catch (e) {
      setError(String(e));
    } finally {
      setComposing(false);
    }
  };

  const setOverride = (
    sceneIdx: number,
    field: keyof SceneOverride,
    value: string | string[] | undefined,
  ) => {
    setOverrides((prev) => {
      const next = { ...prev };
      const cur = { ...(next[sceneIdx] || {}) };
      if (
        value === undefined ||
        value === "" ||
        (Array.isArray(value) && value.length === 0)
      ) {
        delete (cur as Record<string, unknown>)[field];
      } else {
        (cur as Record<string, unknown>)[field] = value;
      }
      if (Object.keys(cur).length === 0) {
        delete next[sceneIdx];
      } else {
        next[sceneIdx] = cur;
      }
      return next;
    });
  };

  if (!jobId) {
    return <div className="p-6 text-rose-300">job ID が URL にありません</div>;
  }

  return (
    <div className="container mx-auto p-6 max-w-5xl space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">VideoStyle 適用 (合成)</h1>
        <Link to="/" className="btn-ghost text-sm">
          プロジェクト一覧へ
        </Link>
      </header>

      {error && (
        <div className="card border border-rose-500/40 text-rose-200 text-sm whitespace-pre-wrap">
          {error}
        </div>
      )}

      {doneScreenplayPath && (
        <div className="card border border-emerald-500/40">
          <h3 className="font-semibold text-emerald-300 mb-2">
            ✓ 完全台本を生成しました
          </h3>
          <div className="text-sm break-all">
            生成台本: <span className="font-mono">{doneScreenplayPath}</span>
          </div>
          <div className="mt-3 flex gap-2">
            <button className="btn-primary" onClick={() => navigate("/")}>
              プロジェクト一覧へ
            </button>
            <button
              className="btn-ghost"
              onClick={() => setDoneScreenplayPath(null)}
            >
              続けて別 Style で再合成
            </button>
          </div>
        </div>
      )}

      <section className="card">
        <h2 className="font-semibold mb-3">1. VideoStyle を選択</h2>
        {styles.length === 0 ? (
          <div className="text-sm text-slate-400">
            VideoStyle が登録されていません (screenplays/styles/ にファイルなし)
          </div>
        ) : (
          <ul className="space-y-2">
            {styles.map((s) => {
              const active = selectedStyle === s.name;
              return (
                <li
                  key={s.name}
                  className={`p-3 rounded border cursor-pointer transition ${
                    active
                      ? "border-emerald-500 bg-emerald-900/20"
                      : "border-slate-700 hover:border-slate-500"
                  }`}
                  onClick={() => setSelectedStyle(s.name)}
                >
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <span className="font-medium text-emerald-200">
                      {s.name}
                    </span>
                    <span className="text-xs text-slate-400">{s.format}</span>
                    <span className="text-xs text-slate-400">
                      anim: {s.animation_style}
                    </span>
                  </div>
                  <div className="text-xs text-slate-400 mt-1">
                    キャラ: {s.characters.map((c) => c.name).join(", ")} · 服装:{" "}
                    {Object.keys(s.wardrobe_continuity).join(", ")} · ロケ:{" "}
                    {Object.keys(s.location_continuity).join(", ")}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {selected && (
        <section className="card">
          <h2 className="font-semibold mb-3">
            2. シーン別オーバーライド (任意)
          </h2>
          {!job ? (
            <div className="text-sm text-slate-400">読み込み中...</div>
          ) : !job.screenplay_path ? (
            <div className="text-sm text-rose-300">
              ジョブが完了していません (screenplay_path が null)
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-xs text-slate-400">
                各シーンで wardrobe / location / tags を VideoStyle
                のデフォルトから
                差し替えられます。空のまま合成を実行すれば全シーンに style の
                デフォルト値が適用されます。
              </div>
              {/* 抽象台本は API 経由で取得していないので、シーン数は
                  job.phases から推測できないため、override 行は最低 1 行表示 */}
              <SceneOverrideTable
                style={selected}
                overrides={overrides}
                onChange={setOverride}
              />
            </div>
          )}
        </section>
      )}

      <section className="card">
        <h2 className="font-semibold mb-3">3. 合成実行</h2>
        <button
          className="btn-primary"
          onClick={onCompose}
          disabled={!selectedStyle || composing || !job?.screenplay_path}
        >
          {composing ? "合成中..." : "完全台本を生成"}
        </button>
        <div className="mt-2 text-xs text-slate-400">
          合成すると {job?.screenplay_path ?? "(未設定)"} に上書き保存されます。
          失敗してもジョブの抽象台本は git で復元可能です。
        </div>
      </section>
    </div>
  );
}

// ─── シーン別 override テーブル ────────────────
function SceneOverrideTable({
  style,
  overrides,
  onChange,
}: {
  style: VideoStyle;
  overrides: Record<number, SceneOverride>;
  onChange: (
    sceneIdx: number,
    field: keyof SceneOverride,
    value: string | string[] | undefined,
  ) => void;
}) {
  // 抽象台本のシーン数が API で取れないので、override 用に 20 行まで表示
  // (実際のシーン数は合成時に決まる、不要な行は空のまま)
  const ROWS = 20;
  const wardrobes = Object.keys(style.wardrobe_continuity);
  const locations = Object.keys(style.location_continuity);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-slate-400">
          <tr className="text-left">
            <th>scene #</th>
            <th>wardrobe</th>
            <th>location</th>
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: ROWS }).map((_, i) => {
            const ov = overrides[i] || {};
            return (
              <tr key={i} className="border-t border-slate-700">
                <td className="py-1 text-slate-400">{i + 1}</td>
                <td>
                  <select
                    className="bg-slate-800 px-2 py-1 rounded text-xs"
                    value={ov.wardrobe ?? ""}
                    onChange={(e) =>
                      onChange(i, "wardrobe", e.target.value || undefined)
                    }
                  >
                    <option value="">(default)</option>
                    {wardrobes.map((w) => (
                      <option key={w} value={w}>
                        {w}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    className="bg-slate-800 px-2 py-1 rounded text-xs"
                    value={ov.location_ref ?? ""}
                    onChange={(e) =>
                      onChange(i, "location_ref", e.target.value || undefined)
                    }
                  >
                    <option value="">(default)</option>
                    {locations.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="text-xs text-slate-500 mt-1">
        ※ 抽象台本のシーン数は合成時に確定します。20 行までの override
        を受け付けます (空欄は default)。
      </div>
    </div>
  );
}
