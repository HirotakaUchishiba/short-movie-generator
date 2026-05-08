"""Phase 4: backfill_experiment_assignments_video_id のテスト。"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def test_backfill_replaces_ts_with_video_id(isolated_db):
    db = isolated_db
    db.insert_experiment_assignment(
        video_id="20260508_120000", axis="hook_type",
        selected_value="共感型", strategy="active_exploit",
    )
    db.insert_experiment_assignment(
        video_id="20260508_120000", axis="tone",
        selected_value="casual", strategy="active_explore",
    )
    updated = db.backfill_experiment_assignments_video_id(
        ts="20260508_120000", video_id="abc123def456",
    )
    assert updated == 2
    rows = db.list_experiment_assignments(video_id="abc123def456")
    assert len(rows) == 2
    # 元の ts を持つ行は無くなっている
    assert db.list_experiment_assignments(video_id="20260508_120000") == []


def test_backfill_returns_zero_when_no_match(isolated_db):
    db = isolated_db
    n = db.backfill_experiment_assignments_video_id(
        ts="no_such_ts", video_id="vidx",
    )
    assert n == 0
