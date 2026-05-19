// StageTTS.tsx から抽出 (= §3.1.3 sub-component 分離)。
//
// ElevenLabs に実送信される連結後の文字列を可視化するセクション。各 line を
// 色違いで描画し、line 間の separator (= 半角スペース×2) は "·" で表示する。
// screenplay 編集に追随して再 fetch する。

import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";
import { useShellCtx } from "../StageGate";

export function TtsSourcePreview() {
  const ctx = useShellCtx();
  const ts = ctx.detail.timestamp;
  const sp = ctx.detail.screenplay;
  const [data, setData] = useState<{
    text: string;
    char_count: number;
    separator: string;
    line_specs: {
      scene_idx: number;
      line_idx: number;
      char_start: number;
      char_end: number;
    }[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(true);

  // screenplay 内容が変わったら refetch (slider/text編集後の即時反映)
  const screenplayKey = useMemo(() => {
    const lines: string[] = [];
    sp.scenes.forEach((s) =>
      (s.lines ?? []).forEach((l) => lines.push(l.text)),
    );
    return lines.join("|");
  }, [sp]);

  useEffect(() => {
    let cancel = false;
    setError(null);
    api
      .ttsSource(ts)
      .then((d) => {
        if (!cancel) setData(d);
      })
      .catch((e) => {
        if (!cancel) setError(String(e));
      });
    return () => {
      cancel = true;
    };
  }, [ts, screenplayKey]);

  if (error) {
    return (
      <div className="card border-rose-700/40 bg-rose-900/10 mt-4 text-xs text-rose-200">
        TTS送信原文の取得失敗: {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card border-sky-700/40 bg-sky-900/10 mt-4 text-xs text-slate-400">
        TTS送信原文を取得中...
      </div>
    );
  }

  // 各 line を別色で、separator は "·" で可視化したセグメントに分解
  type Seg = {
    kind: "line" | "sep";
    text: string;
    idx?: number;
    key: string;
  };
  const segs: Seg[] = [];
  let cursor = 0;
  data.line_specs.forEach((spec, i) => {
    if (spec.char_start > cursor) {
      segs.push({
        kind: "sep",
        text: data.text.slice(cursor, spec.char_start),
        key: `sep-${cursor}-${spec.char_start}`,
      });
    }
    segs.push({
      kind: "line",
      text: data.text.slice(spec.char_start, spec.char_end),
      idx: i,
      key: `line-${i}`,
    });
    cursor = spec.char_end;
  });
  if (cursor < data.text.length) {
    segs.push({
      kind: "sep",
      text: data.text.slice(cursor),
      key: `sep-tail-${cursor}`,
    });
  }

  // separator を点滅文字で見える化
  const renderSep = (s: string) =>
    s.replace(/ /g, "·").replace(/\t/g, "→").replace(/\n/g, "↵\n");

  return (
    <div className="card border-sky-700/40 bg-sky-900/10 mt-4">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <h3 className="font-semibold text-sky-200">
            TTS送信原文 (ElevenLabs に実送信される文字列)
          </h3>
          <p className="text-[11px] text-slate-400 mt-0.5">
            <span className="font-mono">{data.char_count}</span> 文字 ·{" "}
            <span className="font-mono">{data.line_specs.length}</span> line ·
            区切り{" "}
            <span className="font-mono bg-slate-800 px-1 rounded">
              "{renderSep(data.separator)}"
            </span>
          </p>
        </div>
        <button
          className="btn-ghost text-xs"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "折りたたむ" : "展開"}
        </button>
      </div>
      {open && (
        <div className="mt-1 p-3 rounded bg-slate-950/70 border border-slate-800 font-mono text-[13px] leading-7 break-all whitespace-pre-wrap">
          {segs.map((s) =>
            s.kind === "line" ? (
              <span
                key={s.key}
                className={
                  ((s.idx ?? 0) % 2 === 0
                    ? "bg-emerald-900/30 text-emerald-100"
                    : "bg-sky-900/30 text-sky-100") + " px-0.5 rounded-sm"
                }
                title={`line #${s.idx} (${s.text.length}字)`}
              >
                {s.text}
              </span>
            ) : (
              <span key={s.key} className="text-slate-500" title="separator">
                {renderSep(s.text)}
              </span>
            ),
          )}
        </div>
      )}
    </div>
  );
}
