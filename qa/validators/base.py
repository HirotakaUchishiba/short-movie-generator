"""Phase 2 validator の共通型。

Phase 1 の ``qa.validators_provisional.ValidationResult`` を踏襲しつつ、
``scene_idx`` / ``line_idx`` / ``tag`` を必須メタ化することで、auto_loop が
**シーン単位 retry** を判断できるようにする。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValidationResult:
    """1 validator の判定。

    Attributes:
        passed: True なら ok、False なら fail。
        score: 0.0 (= 完全 fail) - 1.0 (= 完璧)。retry 順位付け用。
        reason: fail 時の人間 / Slack 表示向け 1 行説明。
        metrics: 検出した数値 (= silence_ratio / clip_peak_db / etc)。
        scene_idx / line_idx: 失敗の局所化 (None なら stage 全体)。
        tag: ``qa.categories.QA_FAILURE_TAGS`` のいずれか。fail 時のみ意味あり。
    """
    passed: bool
    score: float
    reason: str
    metrics: dict[str, float] = field(default_factory=dict)
    scene_idx: int | None = None
    line_idx: int | None = None
    tag: str | None = None


def passed_result(score: float = 1.0, reason: str = "ok",
                  metrics: dict[str, float] | None = None,
                  scene_idx: int | None = None,
                  line_idx: int | None = None) -> ValidationResult:
    return ValidationResult(
        passed=True, score=score, reason=reason,
        metrics=metrics or {},
        scene_idx=scene_idx, line_idx=line_idx,
    )


def failed_result(score: float, reason: str, tag: str,
                  metrics: dict[str, float] | None = None,
                  scene_idx: int | None = None,
                  line_idx: int | None = None) -> ValidationResult:
    return ValidationResult(
        passed=False, score=score, reason=reason,
        metrics=metrics or {}, tag=tag,
        scene_idx=scene_idx, line_idx=line_idx,
    )


def skipped_result(reason: str = "skipped (dependency missing)",
                   scene_idx: int | None = None,
                   line_idx: int | None = None) -> ValidationResult:
    """ML モデル等の optional 依存が解決できない場合に返す pass。

    auto_loop は ``passed=True`` を見て継続するが、reason 経由で運用者が
    気付ける形にする。
    """
    return ValidationResult(
        passed=True, score=0.0, reason=reason,
        scene_idx=scene_idx, line_idx=line_idx,
    )
