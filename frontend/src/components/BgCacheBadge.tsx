import { useEffect, useState } from "react";
import { api } from "../api";
import { useShellCtx } from "./StageGate";

interface CacheInfo {
  cache_key: string;
  cached: boolean;
  hit_count?: number;
  created_at?: string;
  last_used_at?: string;
}

// Stage 3 シーンカードに「♻️ キャッシュ再利用候補」バッジを表示する。
// 現状の合成入力 (background_prompt + character refs sha + location sha + Imagen
// モデル ID) から派生したキーがグローバルキャッシュに存在すれば、再生成時に
// Imagen API 呼び出しがスキップされる旨を視覚化する。
export default function BgCacheBadge({ sIdx }: { sIdx: number }) {
  const ctx = useShellCtx();
  const [info, setInfo] = useState<CacheInfo | null>(null);
  const regen = ctx.detail.progress.stages.bg.regen_count;

  useEffect(() => {
    let cancel = false;
    api
      .bgCacheInfo(ctx.detail.timestamp, sIdx)
      .then((d) => {
        if (!cancel) setInfo(d);
      })
      .catch(() => {});
    return () => {
      cancel = true;
    };
  }, [ctx.detail.timestamp, sIdx, regen]);

  if (!info) return null;

  if (info.cached) {
    return (
      <span
        className="text-[10px] bg-emerald-900/40 text-emerald-200 border border-emerald-500/30 rounded px-1.5 py-0.5"
        title={[
          `♻️ キャッシュ内に同入力の画像あり`,
          `key: ${info.cache_key}`,
          info.hit_count != null ? `hit_count: ${info.hit_count}` : "",
          info.last_used_at ? `last_used: ${info.last_used_at}` : "",
        ]
          .filter(Boolean)
          .join("\n")}
      >
        ♻️ 再利用候補 ({info.hit_count ?? 0} hits)
      </span>
    );
  }
  return (
    <span
      className="text-[10px] bg-slate-800/60 text-slate-400 border border-slate-700 rounded px-1.5 py-0.5"
      title={`新規生成 (cache key: ${info.cache_key})`}
    >
      新規生成
    </span>
  );
}
