// 全 stage 共通の cache decision フローのトップレベル。
// 単一責務: 「scan / 判断 / 生成」の状態管理 + 子コンポーネントの組み立て。
//
// 実際の API 呼び出しは props で渡された StageCacheApi を経由する (= 依存注入)。
// stage 別の preview / metadata 描画は presenter 経由 (= UI 差分の単一注入点)。
import { useEffect, useMemo, useState } from "react";
import BulkDecisionBar from "./BulkDecisionBar";
import GenerateRemainingBar from "./GenerateRemainingBar";
import SceneDecisionCard from "./SceneDecisionCard";
import type { CachePresenter, SceneDecision } from "./types";
import type { DecisionsResponse } from "../../types";

interface StageCacheApi<TMeta> {
  scanCache: (ts: string) => Promise<DecisionsResponse<TMeta>>;
  decisions: (ts: string) => Promise<DecisionsResponse<TMeta>>;
  useCache: (
    ts: string,
    sceneIdx: number,
    key: string,
  ) => Promise<{ ok: true; decision: "cache"; key: string }>;
  queueFresh: (
    ts: string,
    sceneIdx: number,
  ) => Promise<{ ok: true; decision: "fresh" }>;
  sceneRescan: (
    ts: string,
    sceneIdx: number,
  ) => Promise<{ ok: true; scene_decision: SceneDecision<TMeta> }>;
  decisionsBulk: (
    ts: string,
    action: "all-cache" | "all-fresh",
  ) => Promise<{
    ok: true;
    summary: { adopted: number; queued_fresh: number; errors: unknown[] };
    scene_decisions: Record<string, SceneDecision<TMeta>>;
  }>;
  generateRemaining: (
    ts: string,
  ) => Promise<{ job_id: string; fresh_scenes: number[] }>;
}

interface Props<TMeta> {
  ts: string;
  sceneCount: number;
  api: StageCacheApi<TMeta>;
  presenter: CachePresenter<TMeta>;
  /** 「残りの〇〇を生成」ボタンの「〇〇」(= "動画" / "画像" など)。 */
  assetLabel: string;
  /** generate-remaining 完了後に親 (StageGate) を reload するためのコールバック。 */
  onGenerated: () => Promise<void>;
}

export default function CacheDecisionFlow<TMeta>({
  ts,
  sceneCount,
  api,
  presenter,
  assetLabel,
  onGenerated,
}: Props<TMeta>) {
  const [decisions, setDecisions] = useState<DecisionsResponse<TMeta> | null>(
    null,
  );
  const [scanning, setScanning] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 初回マウント: decisions を取得し、未スキャンなら自動 scan する。
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cur = await api.decisions(ts);
        if (cancelled) return;
        if (cur.cache_scanned_at === null) {
          setScanning(true);
          const fresh = await api.scanCache(ts);
          if (cancelled) return;
          setDecisions(fresh);
          setScanning(false);
        } else {
          setDecisions(cur);
        }
      } catch (e) {
        if (!cancelled) {
          setError(String(e));
          setScanning(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ts, api]);

  const refresh = async () => {
    const next = await api.decisions(ts);
    setDecisions(next);
  };

  const onRescan = async () => {
    setScanning(true);
    setError(null);
    try {
      const fresh = await api.scanCache(ts);
      setDecisions(fresh);
    } catch (e) {
      setError(String(e));
    } finally {
      setScanning(false);
    }
  };

  const onBulk = async (action: "all-cache" | "all-fresh") => {
    setError(null);
    try {
      await api.decisionsBulk(ts, action);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const onGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      await api.generateRemaining(ts);
      await onGenerated();
    } catch (e) {
      setError(String(e));
    } finally {
      setGenerating(false);
    }
  };

  const sceneDecisions = decisions?.scene_decisions ?? {};
  const decidedCount = useMemo(() => {
    let n = 0;
    for (let i = 0; i < sceneCount; i++) {
      const d = sceneDecisions[String(i)]?.decision;
      if (d === "cache" || d === "fresh") n++;
    }
    return n;
  }, [sceneDecisions, sceneCount]);
  const freshCount = useMemo(
    () =>
      Object.values(sceneDecisions).filter((d) => d.decision === "fresh")
        .length,
    [sceneDecisions],
  );
  const candidatesCount = useMemo(
    () =>
      Object.values(sceneDecisions).filter(
        (d) => (d.candidates?.length ?? 0) > 0,
      ).length,
    [sceneDecisions],
  );
  const totalFreshCost = useMemo<number | null>(() => {
    let cost = 0;
    let anyKnown = false;
    for (let i = 0; i < sceneCount; i++) {
      const d = sceneDecisions[String(i)];
      if (!d || d.decision === "cache") continue;
      const c = presenter.costForScene(i);
      if (c == null) continue;
      cost += c;
      anyKnown = true;
    }
    return anyKnown ? cost : null;
  }, [sceneDecisions, sceneCount, presenter]);

  if (!decisions || (decisions.cache_scanned_at === null && scanning)) {
    return (
      <div className="card text-center py-10">
        <h3 className="font-semibold text-lg mb-2">
          {scanning ? "🔍 キャッシュをスキャン中..." : "状態を読み込み中..."}
        </h3>
        {error && <div className="text-rose-400 text-xs mt-3">{error}</div>}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <BulkDecisionBar
        decidedCount={decidedCount}
        totalCount={sceneCount}
        candidatesCount={candidatesCount}
        totalFreshCost={totalFreshCost}
        scanning={scanning}
        busy={generating}
        onRescan={onRescan}
        onBulk={onBulk}
      />

      {error && <div className="text-rose-400 text-xs">{error}</div>}

      <div className="flex flex-col gap-3">
        {Array.from({ length: sceneCount }, (_, i) => (
          <SceneDecisionCard
            key={i}
            sceneIdx={i}
            decision={sceneDecisions[String(i)]}
            presenter={presenter}
            onUseCache={async (key) => {
              await api.useCache(ts, i, key);
              await refresh();
            }}
            onQueueFresh={async () => {
              await api.queueFresh(ts, i);
              await refresh();
            }}
            onRescan={async () => {
              await api.sceneRescan(ts, i);
              await refresh();
            }}
          />
        ))}
      </div>

      <GenerateRemainingBar
        totalCount={sceneCount}
        decidedCount={decidedCount}
        freshCount={freshCount}
        totalFreshCost={totalFreshCost}
        generating={generating}
        busy={scanning}
        assetLabel={assetLabel}
        onGenerate={onGenerate}
      />
    </div>
  );
}
