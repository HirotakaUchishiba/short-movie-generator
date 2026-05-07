"""Phase 1: 1 日 / 1 ヶ月の cost cap と video count cap を集計する。

`cost_records.jsonl` (= 全 stage の API 課金履歴) と
`analytics.generation_records.created_at` を統合して、auto_loop.py が
新規 project を起動する前の capacity check に使う。

cap = 0 は無制限の意味。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import config
from analytics import db as _adb
from cost_tracking import records

logger = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    """auto_loop の cap 抵触で raise される。"""

    def __init__(self, message: str, status: "BudgetStatus | None" = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class BudgetStatus:
    daily_cost_usd: float
    monthly_cost_usd: float
    daily_video_count: int
    daily_cap_usd: float
    monthly_cap_usd: float
    daily_video_cap: int

    @property
    def daily_cost_exceeded(self) -> bool:
        return self.daily_cap_usd > 0 and self.daily_cost_usd >= self.daily_cap_usd

    @property
    def monthly_cost_exceeded(self) -> bool:
        return (self.monthly_cap_usd > 0
                and self.monthly_cost_usd >= self.monthly_cap_usd)

    @property
    def daily_video_exceeded(self) -> bool:
        return (self.daily_video_cap > 0
                and self.daily_video_count >= self.daily_video_cap)

    @property
    def is_blocked(self) -> bool:
        return (self.daily_cost_exceeded
                or self.monthly_cost_exceeded
                or self.daily_video_exceeded)

    def reasons(self) -> list[str]:
        out: list[str] = []
        if self.daily_cost_exceeded:
            out.append(
                f"daily cost cap: ${self.daily_cost_usd:.2f} "
                f">= ${self.daily_cap_usd:.2f}",
            )
        if self.monthly_cost_exceeded:
            out.append(
                f"monthly cost cap: ${self.monthly_cost_usd:.2f} "
                f">= ${self.monthly_cap_usd:.2f}",
            )
        if self.daily_video_exceeded:
            out.append(
                f"daily video cap: {self.daily_video_count} "
                f">= {self.daily_video_cap}",
            )
        return out


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_day(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _sum_cost_since(since: datetime) -> float:
    """cost_records.jsonl の ``timestamp >= since`` の cost_usd を合計する。

    cost_records.records.append() が UTC ISO 形式 ("2026-05-08T00:00:00+00:00")
    で書き込んでいる前提。同一形式同士なら文字列比較で時系列順を表現できる。
    """
    since_iso = since.isoformat(timespec="seconds")
    total = 0.0
    for rec in records.iter_all():
        if rec.timestamp >= since_iso:
            total += float(rec.cost_usd)
    return total


def _count_videos_since(since: datetime) -> int:
    """``generation_records.created_at >= since`` の行数を返す。

    SQLite の CURRENT_TIMESTAMP は UTC で "YYYY-MM-DD HH:MM:SS" 形式。
    """
    since_sql = since.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _adb.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM generation_records "
                "WHERE created_at >= ?",
                (since_sql,),
            ).fetchone()
    except Exception as e:
        # DB 障害は cap = 0 扱いで auto_loop は通す (= cost ガードはあるので上限は守られる)。
        logger.warning("[budget] _count_videos_since failed: %s", e)
        return 0
    return int(row["c"]) if row else 0


def current_status(now: datetime | None = None) -> BudgetStatus:
    """現在の累積 cost / video カウントと cap を返す。"""
    now = now or _now_utc()
    return BudgetStatus(
        daily_cost_usd=_sum_cost_since(_start_of_day(now)),
        monthly_cost_usd=_sum_cost_since(_start_of_month(now)),
        daily_video_count=_count_videos_since(_start_of_day(now)),
        daily_cap_usd=config.DAILY_COST_CAP_USD,
        monthly_cap_usd=config.MONTHLY_COST_CAP_USD,
        daily_video_cap=config.DAILY_VIDEO_CAP,
    )


def assert_within_caps(now: datetime | None = None) -> BudgetStatus:
    """auto_loop の冒頭で呼ぶ。cap 抵触なら ``BudgetExceeded`` を raise。

    Returns:
        BudgetStatus: ブロック状態を残したい場合のために返す。
    """
    status = current_status(now)
    if status.is_blocked:
        reasons = "; ".join(status.reasons())
        raise BudgetExceeded(
            f"auto_loop budget exceeded: {reasons}",
            status=status,
        )
    return status
