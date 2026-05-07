"""Phase 3: improvement.strategy の dispatch テスト。"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_strategy(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def _seed_axis_performance(db, axis_value: str, *, hook="A", n=5,
                           completion=0.5):
    """v_axis_performance に乗るよう screenplays / videos / posts / metrics を仕込む。

    軸は hook_type を試したいので、screenplays.hook_type に値を入れる + 必要な
    join chain を埋める。
    """
    sp_id = f"sp_{axis_value}"
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO screenplays (id, path, name, sha256, created_at,
               raw_json, hook_type)
               VALUES (?, '/x', 'x', ?, datetime('now'), '{}', ?)""",
            (sp_id, sp_id + "_sha", axis_value),
        )
        for i in range(n):
            v_id = f"v_{axis_value}_{i}"
            conn.execute(
                """INSERT INTO videos (id, screenplay_id, output_path,
                   generated_at)
                   VALUES (?, ?, '/x', datetime('now'))""",
                (v_id, sp_id),
            )
            p_id = f"p_{axis_value}_{i}"
            conn.execute(
                """INSERT INTO posts (id, video_id, platform, platform_post_id,
                   posted_at, registered_at)
                   VALUES (?, ?, 'youtube', ?, datetime('now', '-2 days'),
                           datetime('now'))""",
                (p_id, v_id, p_id),
            )
            conn.execute(
                """INSERT INTO post_metrics (post_id, fetched_at, views,
                   completion_rate, saves)
                   VALUES (?, datetime('now'), 1000, ?, 50)""",
                (p_id, completion),
            )


def test_baseline_returns_empty(monkeypatch, isolated_strategy):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "baseline")
    from improvement.strategy import select_assignments_for_video
    assert select_assignments_for_video() == {}


def test_shadow_returns_assignments_when_data_exists(
    monkeypatch, isolated_strategy,
):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "shadow")
    monkeypatch.setattr("config.BANDIT_AXES", ("hook_type",))
    monkeypatch.setattr("config.BANDIT_EPSILON", 0.0)  # 必ず exploit
    db = isolated_strategy
    _seed_axis_performance(db, "共感型", n=3, completion=0.4)
    _seed_axis_performance(db, "結論先出し", n=3, completion=0.6)

    from improvement.strategy import select_assignments_for_video
    out = select_assignments_for_video()
    assert "hook_type" in out
    value, sub = out["hook_type"]
    assert value == "結論先出し"  # 平均 reward が高い
    assert sub == "exploit"


def test_record_assignments_writes_strategy_with_overall_prefix(
    monkeypatch, isolated_strategy,
):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "active")
    db = isolated_strategy
    from improvement.strategy import record_assignments
    record_assignments("ts1", {"hook_type": ("結論先出し", "exploit")})
    rows = db.list_experiment_assignments(video_id="ts1")
    assert len(rows) == 1
    assert rows[0]["strategy"] == "active_exploit"


def test_record_assignments_baseline_skips(monkeypatch, isolated_strategy):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "baseline")
    db = isolated_strategy
    from improvement.strategy import record_assignments
    record_assignments("ts1", {"hook_type": ("x", "exploit")})
    assert db.list_experiment_assignments(video_id="ts1") == []


def test_assignments_skipped_when_no_history(monkeypatch, isolated_strategy):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "shadow")
    monkeypatch.setattr("config.BANDIT_AXES", ("hook_type",))
    from improvement.strategy import select_assignments_for_video
    # データ無し → 空 dict
    assert select_assignments_for_video() == {}
