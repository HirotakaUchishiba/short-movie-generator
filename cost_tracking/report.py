"""コストレポート (実コスト履歴の集約)。

ProjectReport / OverallReport を構築する。集約ロジックは純粋関数化し、
読み出しは ``records.iter_*`` のみに依存する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from cost_tracking import pricebook, records


@dataclass(frozen=True)
class ProjectReport:
    project_ts: str
    record_count: int
    total_usd: float
    total_jpy: float
    per_stage: dict[str, float] = field(default_factory=dict)
    per_provider: dict[str, float] = field(default_factory=dict)
    per_scene: dict[int, float] = field(default_factory=dict)
    generated_at: str = ""


@dataclass(frozen=True)
class OverallReport:
    project_count: int
    record_count: int
    total_usd: float
    total_jpy: float
    per_project: dict[str, float] = field(default_factory=dict)
    per_stage: dict[str, float] = field(default_factory=dict)
    per_provider: dict[str, float] = field(default_factory=dict)
    generated_at: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sum_by(recs: Iterable[records.CostRecord], key) -> dict:
    out: dict = {}
    for r in recs:
        k = key(r)
        if k is None:
            continue
        out[k] = out.get(k, 0.0) + r.cost_usd
    return out


def build_project_report(
    project_ts: str,
    recs: list[records.CostRecord],
    jpy_rate: float,
) -> ProjectReport:
    """純粋関数: records と為替レートからレポートを構築する。"""
    total_usd = sum(r.cost_usd for r in recs)
    return ProjectReport(
        project_ts=project_ts,
        record_count=len(recs),
        total_usd=total_usd,
        total_jpy=total_usd * jpy_rate,
        per_stage=_sum_by(recs, lambda r: r.stage),
        per_provider=_sum_by(recs, lambda r: r.provider),
        per_scene=_sum_by(recs, lambda r: r.scene_index),
        generated_at=_now_iso(),
    )


def build_overall_report(
    recs: list[records.CostRecord],
    jpy_rate: float,
) -> OverallReport:
    """純粋関数: 全 records と為替レートから OverallReport を構築する。"""
    total_usd = sum(r.cost_usd for r in recs)
    per_project = _sum_by(recs, lambda r: r.project_ts)
    return OverallReport(
        project_count=len(per_project),
        record_count=len(recs),
        total_usd=total_usd,
        total_jpy=total_usd * jpy_rate,
        per_project=per_project,
        per_stage=_sum_by(recs, lambda r: r.stage),
        per_provider=_sum_by(recs, lambda r: r.provider),
        generated_at=_now_iso(),
    )


def report_for_project(project_ts: str) -> ProjectReport:
    """指定 project_ts のレコードを集約して ProjectReport を返す。"""
    recs = list(records.iter_filtered(project_ts=project_ts))
    return build_project_report(project_ts, recs, pricebook.jpy_per_usd())


def report_overall(*, since: str | None = None) -> OverallReport:
    """全レコードを集約。``since`` (ISO8601) 以降のみに絞り込み可。"""
    recs = list(records.iter_all())
    if since is not None:
        recs = [r for r in recs if r.timestamp >= since]
    return build_overall_report(recs, pricebook.jpy_per_usd())
