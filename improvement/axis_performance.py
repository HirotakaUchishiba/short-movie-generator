"""Phase 3: ``v_axis_performance`` を読み bandit が必要な reward 履歴を返す。

`metric` の選択: 完視聴率 (= ``avg_completion``) を主軸に、必要なら
``avg_save`` / ``avg_views`` も使える。
"""
from __future__ import annotations

import logging

from analytics import db

logger = logging.getLogger(__name__)


def reward_history_for_axis(
    axis: str, *, metric: str = "avg_completion", limit: int = 200,
    strategy_prefix: str | None = None,
) -> list[tuple[str, float]]:
    """``[(value, reward), ...]`` を返す。bandit.from_history に直接渡せる形。

    ``strategy_prefix`` を渡すと ``v_strategy_performance`` を経由して
    特定 strategy 群 (= "active" / "shadow" / "baseline") のみで集計する。
    Phase 3.5 で shadow/active を別母集団として扱うときに使う。``None`` (= 既定)
    は全 strategy 混合の従来挙動。
    """
    try:
        rows = db.query_axis_performance(
            axis, metric=metric, limit=limit,
            strategy_prefix=strategy_prefix,
        )
    except Exception as e:
        logger.warning("[axis-perf] query failed for %s: %s", axis, e)
        return []
    return [(r["axis_value"], r["metric"]) for r in rows]


def candidates_for_axis(
    axis: str, *, metric: str = "avg_completion",
    min_samples: int = 1, limit: int = 200,
    strategy_prefix: str | None = None,
) -> list[str]:
    """十分なサンプル数を持つ候補値の list を返す。

    ``min_samples`` 未満の値は exploration の対象外 (= 統計が薄すぎる)。
    """
    try:
        rows = db.query_axis_performance(
            axis, metric=metric, limit=limit,
            strategy_prefix=strategy_prefix,
        )
    except Exception as e:
        logger.warning("[axis-perf] candidates failed for %s: %s", axis, e)
        return []
    return [r["axis_value"] for r in rows if r["n"] >= min_samples]
