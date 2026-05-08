"""Phase X-1: record_assignments の scene_idx / composition_id 引数テスト。"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_strategy(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def test_record_assignments_passes_scene_idx_to_db(
    monkeypatch, isolated_strategy,
):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "active")
    db = isolated_strategy
    from improvement.strategy import record_assignments
    record_assignments(
        "ts1", {"hook_type": ("結論先出し", "exploit")},
        scene_idx=3,
        composition_id="0123456789abcdef",
        composition_version="v1",
    )
    rows = db.list_experiment_assignments(video_id="ts1")
    assert len(rows) == 1
    assert rows[0]["scene_idx"] == 3
    assert rows[0]["composition_id"] == "0123456789abcdef"
    assert rows[0]["composition_version"] == "v1"
    assert rows[0]["strategy"] == "active_exploit"


def test_record_assignments_back_compat_without_scene_idx(
    monkeypatch, isolated_strategy,
):
    """既存 auto_loop 経由の呼び出し (= scene_idx 等省略) は NULL で記録。"""
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "shadow")
    db = isolated_strategy
    from improvement.strategy import record_assignments
    record_assignments("ts1", {"hook_type": ("x", "explore")})
    rows = db.list_experiment_assignments(video_id="ts1")
    assert len(rows) == 1
    assert rows[0]["scene_idx"] is None
    assert rows[0]["composition_id"] is None
    assert rows[0]["composition_version"] is None


def test_record_assignments_baseline_skips_even_with_scene_idx(
    monkeypatch, isolated_strategy,
):
    """baseline では scene_idx を渡しても何も書き込まない (= 既存挙動の維持)。"""
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "baseline")
    db = isolated_strategy
    from improvement.strategy import record_assignments
    record_assignments(
        "ts1", {"hook_type": ("x", "exploit")},
        scene_idx=0, composition_id="abcd",
    )
    assert db.list_experiment_assignments(video_id="ts1") == []
