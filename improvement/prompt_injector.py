"""Phase 3: Claude system prompt 用の「過去パフォーマンス + exploration 指示」組み立て。

`auto_loop` から `analyze.run` の `options.instructions` に流し込む文字列を作る。
Claude には:

  1. 過去 30 日の高パフォーマンス傾向 (= 軸別 top 3)
  2. 今回意図的に試す軸と値 (= bandit 由来)

を提示し、「無難な選択」に偏らないよう exploration を強制する。
"""
from __future__ import annotations

import logging

import config
from improvement import axis_performance

logger = logging.getLogger(__name__)


def build_performance_summary(
    *, metric: str = "avg_completion", top_n: int = 3,
) -> str:
    """軸別の高パフォーマンス値を箇条書きで返す。空ならば空文字。"""
    if config.IMPROVEMENT_STRATEGY == "baseline":
        return ""
    lines: list[str] = []
    for axis in config.BANDIT_AXES:
        history = axis_performance.reward_history_for_axis(
            axis, metric=metric, limit=200,
        )
        if not history:
            continue
        # 値ごとの平均 reward
        agg: dict[str, list[float]] = {}
        for value, reward in history:
            agg.setdefault(value, []).append(reward)
        ranked = sorted(
            ((v, sum(rs) / len(rs)) for v, rs in agg.items()),
            key=lambda x: x[1], reverse=True,
        )[:top_n]
        if not ranked:
            continue
        formatted = " > ".join(f"{v} ({r:.1%})" for v, r in ranked)
        lines.append(f"- {axis}: {formatted}")
    if not lines:
        return ""
    return (
        "## 過去 30 日の高パフォーマンス傾向 (avg completion rate)\n"
        + "\n".join(lines)
        + "\n"
    )


def build_exploration_directive(
    assignments: dict[str, tuple[str, str]],
) -> str:
    """``{axis: (value, sub_strategy)}`` から exploration 指示を組み立てる。"""
    if not assignments:
        return ""
    lines = []
    for axis, (value, sub_strategy) in assignments.items():
        marker = (
            "意図的 exploration" if sub_strategy == "explore"
            else "historical best"
        )
        lines.append(f"- {axis}: **{value}** ({marker})")
    return (
        "## 今回意図的に試す軸\n"
        + "\n".join(lines)
        + "\n\n上記の値が成立する範囲で台本構成を組み立ててください。\n"
    )


def compose_instructions(
    assignments: dict[str, tuple[str, str]] | None = None,
    *, base: str | None = None,
) -> str | None:
    """auto_loop から analyze.run の instructions に渡す文字列を組み立てる。

    Returns:
        実質的な内容が無ければ None (= analyze 既存挙動)。
    """
    if config.IMPROVEMENT_STRATEGY == "baseline":
        return base
    parts: list[str] = []
    if base:
        parts.append(base)
    summary = build_performance_summary()
    if summary:
        parts.append(summary)
    if config.IMPROVEMENT_STRATEGY == "active" and assignments:
        directive = build_exploration_directive(assignments)
        if directive:
            parts.append(directive)
    if not parts:
        return base
    return "\n".join(parts)
