"""scene_gen.py から prompt 構築 helper を切り出した module。

将来 PR で _build_background_prompt / _detect_storyboard_image 等の
prompt 関連 helper も本 module に集約する (= 計画書 §3.1.1-a 段階移行)。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
"""

from __future__ import annotations

import config


def augment_animation_prompt(base_prompt: str, kling_duration: float) -> str:
    """Kling の後半が静止するよう、動作を前半に集中させる指示と、
    UI hallucination 抑止 negative 文を末尾に追加する。冪等。"""
    settle_pct = int(config.ACTION_FRONTLOAD_RATIO * 100)
    settle_at = kling_duration * config.ACTION_FRONTLOAD_RATIO
    addon = (
        f". Complete all major actions within the first {settle_pct}% of the clip "
        f"(by approximately {settle_at:.1f}s). In the remaining time, hold the final "
        f"pose with minimal movement so the clip can be cleanly trimmed at the end."
    )

    out = base_prompt
    if "Complete all major actions" not in out:
        out = out + addon

    neg = config.KLING_NEGATIVE_CONSTRAINT
    # 既に同じ negative 文があれば二重追加しない (冪等)
    if neg and neg not in out:
        out = out + ". " + neg

    return out
