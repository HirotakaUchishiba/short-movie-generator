"""Phase 1 cost / video cap の単体テスト。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest


@pytest.fixture
def isolated_budget(tmp_path, monkeypatch):
    cost_path = tmp_path / "cost_records.jsonl"
    monkeypatch.setenv("COST_RECORDS_PATH", str(cost_path))
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()

    # cap を test 用に下げる
    import config
    monkeypatch.setattr(config, "DAILY_COST_CAP_USD", 5.0)
    monkeypatch.setattr(config, "MONTHLY_COST_CAP_USD", 50.0)
    monkeypatch.setattr(config, "DAILY_VIDEO_CAP", 3)

    from cost_tracking import budget
    return budget, _db, cost_path


def _append_cost(path, *, cost_usd: float, ts_iso: str) -> None:
    rec = {
        "record_id": "x",
        "timestamp": ts_iso,
        "project_ts": None,
        "stage": "tts",
        "operation": "generate",
        "scene_index": None,
        "line_index": None,
        "provider": "elevenlabs",
        "model": "eleven_v3",
        "units": {"characters": 100.0},
        "unit_prices": {"usd_per_credit": 0.0},
        "cost_usd": cost_usd,
        "metadata": {},
    }
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def test_status_within_caps(isolated_budget) -> None:
    budget, _, cost_path = isolated_budget
    today_iso = datetime.now(timezone.utc).replace(hour=12).isoformat(timespec="seconds")
    _append_cost(cost_path, cost_usd=1.0, ts_iso=today_iso)
    status = budget.current_status()
    assert status.daily_cost_usd == pytest.approx(1.0)
    assert not status.is_blocked


def test_daily_cost_exceeded(isolated_budget) -> None:
    budget, _, cost_path = isolated_budget
    today_iso = datetime.now(timezone.utc).replace(hour=10).isoformat(timespec="seconds")
    _append_cost(cost_path, cost_usd=6.0, ts_iso=today_iso)
    status = budget.current_status()
    assert status.daily_cost_exceeded
    assert status.is_blocked


def test_monthly_cost_exceeded(isolated_budget) -> None:
    budget, _, cost_path = isolated_budget
    # 今日と別日 (= daily に乗らない過去日) に monthly cap を超える金額を入れる。
    # current_status(now=...) で時刻を固定して当月内の関係を保証する。
    fixed_now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    past_day_in_month = datetime(2026, 5, 3, 10, 0, 0, tzinfo=timezone.utc)
    _append_cost(cost_path, cost_usd=51.0,
                 ts_iso=past_day_in_month.isoformat(timespec="seconds"))
    status = budget.current_status(now=fixed_now)
    assert status.monthly_cost_exceeded
    assert not status.daily_cost_exceeded
    assert status.is_blocked


def test_daily_video_exceeded(isolated_budget) -> None:
    budget, db, _ = isolated_budget
    # 同日に 3 件以上 generation_records を作る
    for ts in ("v1", "v2", "v3", "v4"):
        db.append_stage_run(
            ts=ts, stage="script",
            started_at="x", ended_at="y", status="completed",
        )
    status = budget.current_status()
    assert status.daily_video_count >= 4
    assert status.daily_video_exceeded
    assert status.is_blocked


def test_assert_within_caps_raises_when_blocked(isolated_budget) -> None:
    budget, _, cost_path = isolated_budget
    today_iso = datetime.now(timezone.utc).replace(hour=10).isoformat(timespec="seconds")
    _append_cost(cost_path, cost_usd=10.0, ts_iso=today_iso)
    with pytest.raises(budget.BudgetExceeded) as exc:
        budget.assert_within_caps()
    assert exc.value.status is not None
    assert exc.value.status.daily_cost_exceeded


def test_assert_within_caps_returns_status_when_clear(isolated_budget) -> None:
    budget, _, _ = isolated_budget
    status = budget.assert_within_caps()
    assert status.is_blocked is False


def test_cap_zero_means_unlimited(isolated_budget, monkeypatch) -> None:
    budget, _, cost_path = isolated_budget
    import config
    monkeypatch.setattr(config, "DAILY_COST_CAP_USD", 0.0)
    today_iso = datetime.now(timezone.utc).replace(hour=10).isoformat(timespec="seconds")
    _append_cost(cost_path, cost_usd=999.0, ts_iso=today_iso)
    status = budget.current_status()
    assert status.daily_cost_usd >= 999.0
    assert not status.daily_cost_exceeded


def test_old_records_ignored(isolated_budget) -> None:
    """昨日のコストは daily に入らない。"""
    budget, _, cost_path = isolated_budget
    yesterday_iso = "2024-01-01T12:00:00+00:00"
    _append_cost(cost_path, cost_usd=100.0, ts_iso=yesterday_iso)
    status = budget.current_status()
    assert status.daily_cost_usd == 0.0
    # ただし monthly も今月外なので 0
    assert status.monthly_cost_usd == 0.0
