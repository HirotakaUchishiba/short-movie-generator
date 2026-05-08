"""Phase 3: IMPROVEMENT_STRATEGY (baseline / shadow / active) の dispatch。

auto_loop は以下の 2 関数だけを叩けば良い:

    assignments = strategy.select_assignments_for_video(seed=ref_sha)
    strategy.record_assignments(ts, assignments)

baseline: 空 dict が返る、record も何もしない。
shadow:   bandit が選択 → DB に記録 (但し prompt には載せない)。
active:   shadow + prompt_injector で analyze.run の instructions に注入。

並列実行の挙動:
    複数の auto_loop プロセスが同時に走る場合、それぞれ独立に
    ``select_assignments_for_video()`` を呼ぶため、同じ DB スナップショットを
    見て同じ exploit arm を選びうる。ε-greedy は期待値ベースで正しく動くが、
    並列度が高いと exploration が偏る点に注意。
"""
from __future__ import annotations

import logging
import random

import config
from analytics import db
from improvement import axis_performance
from improvement.bandit import EpsilonGreedyBandit

logger = logging.getLogger(__name__)


def select_assignments_for_video(
    *, seed: str | None = None,
    rng: random.Random | None = None,
) -> dict[str, tuple[str, str]]:
    """各軸ごとに「今回試す値」を ε-greedy で選び返す。

    ``IMPROVEMENT_STRATEGY=baseline`` のときは空 dict。

    Args:
        seed: 文字列 (= ref sha など)。指定すると ``random.Random(seed)`` を使い、
            同じ seed + 同じ DB state から同じ assignments を再現できる
            (= 本番デバッグ / 監査ログ用)。``rng`` 指定時は無視される。
        rng: テスト用の明示 ``random.Random`` 注入経路。

    Returns:
        ``{axis: (value, sub_strategy)}`` — sub_strategy は ``"explore"`` /
        ``"exploit"``。
    """
    if config.IMPROVEMENT_STRATEGY == "baseline":
        return {}

    if rng is None and seed is not None:
        rng = random.Random(seed)

    out: dict[str, tuple[str, str]] = {}
    for axis in config.BANDIT_AXES:
        history = axis_performance.reward_history_for_axis(
            axis, metric="avg_completion", limit=200,
        )
        if not history:
            continue
        bandit = EpsilonGreedyBandit(
            epsilon=config.BANDIT_EPSILON, rng=rng,
        )
        bandit.from_history(history)
        candidates = sorted({v for v, _ in history})
        if not candidates:
            continue
        try:
            value, sub_strategy = bandit.select(candidates)
        except ValueError:
            continue
        out[axis] = (value, sub_strategy)
    return out


def record_assignments(
    video_id: str,
    assignments: dict[str, tuple[str, str]],
    *,
    scene_idx: int | None = None,
    composition_id: str | None = None,
    composition_version: str | None = None,
) -> None:
    """experiment_assignments テーブルに 1 video 分の選択を保存する。

    strategy 列は ``<overall_strategy>_<sub_strategy>`` 形式 (例:
    ``shadow_explore`` / ``active_exploit``)。baseline は空 dict なので
    そもそもここには来ない。

    Phase X-1 で追加された keyword 引数:
        scene_idx: scene 粒度の bandit を回す段階 (= X-3) で 1 scene 分の
            記録を残すために使う。X-1 段階の auto_loop は動画粒度のままなので
            None で呼ばれ、experiment_assignments には NULL で書かれる。
        composition_id / composition_version: ``composition_id.compute_composition_id``
            の戻り値と "v1" 等のバージョンタグ。X-1 段階では cache 解析と紐付け
            たい時に上層で計算して渡す形 (= 動画粒度書き込みなら通常 None)。
    """
    overall = config.IMPROVEMENT_STRATEGY
    if overall == "baseline" or not assignments:
        return
    for axis, (value, sub_strategy) in assignments.items():
        full = f"{overall}_{sub_strategy}"
        try:
            db.insert_experiment_assignment(
                video_id=video_id, axis=axis,
                selected_value=value, strategy=full,
                scene_idx=scene_idx,
                composition_id=composition_id,
                composition_version=composition_version,
            )
        except Exception as e:
            logger.warning(
                "[strategy] record_assignments failed (%s=%s): %s",
                axis, value, e,
            )
