"""Phase 3: experiment_assignments + v_axis_performance / query_axis_performance のテスト。"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def _seed_chain(db, *, ts: str, hook: str, completion: float,
                posted_days_ago: int = 2,
                tone: str = "casual",
                dominant_emotion: str = "喜び",
                theme: str = "career_change"):
    sp_id = f"sp_{ts}"
    v_id = f"v_{ts}"
    p_id = f"p_{ts}"
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO screenplays (id, path, name, sha256, created_at,
               raw_json, hook_type, tone, dominant_emotion, theme)
               VALUES (?, '/x', 'x', ?, datetime('now'), '{}',
                       ?, ?, ?, ?)""",
            (sp_id, sp_id + "_sha", hook, tone, dominant_emotion, theme),
        )
        conn.execute(
            """INSERT INTO videos (id, screenplay_id, output_path, generated_at)
               VALUES (?, ?, '/x', datetime('now'))""",
            (v_id, sp_id),
        )
        conn.execute(
            """INSERT INTO posts (id, video_id, platform, platform_post_id,
               posted_at, registered_at)
               VALUES (?, ?, 'youtube', ?,
                       datetime('now', '-' || ? || ' days'),
                       datetime('now'))""",
            (p_id, v_id, p_id, posted_days_ago),
        )
        conn.execute(
            """INSERT INTO post_metrics (post_id, fetched_at, views,
               completion_rate, saves)
               VALUES (?, datetime('now'), 1000, ?, 100)""",
            (p_id, completion),
        )


def test_experiment_assignment_insert_and_list(isolated_db):
    db = isolated_db
    fid = db.insert_experiment_assignment(
        video_id="ts1", axis="hook_type",
        selected_value="共感型", strategy="active_explore",
    )
    assert fid > 0
    rows = db.list_experiment_assignments(video_id="ts1")
    assert len(rows) == 1
    assert rows[0]["axis"] == "hook_type"
    assert rows[0]["strategy"] == "active_explore"


def test_experiment_assignment_filter_by_strategy(isolated_db):
    db = isolated_db
    db.insert_experiment_assignment(
        video_id="t1", axis="tone",
        selected_value="x", strategy="shadow_explore",
    )
    db.insert_experiment_assignment(
        video_id="t2", axis="tone",
        selected_value="y", strategy="active_exploit",
    )
    assert len(db.list_experiment_assignments(strategy="shadow_explore")) == 1
    assert len(db.list_experiment_assignments(strategy="active_exploit")) == 1


def test_query_axis_performance_returns_grouped_rows(isolated_db):
    db = isolated_db
    _seed_chain(db, ts="t1", hook="共感型", completion=0.4)
    _seed_chain(db, ts="t2", hook="共感型", completion=0.5)
    _seed_chain(db, ts="t3", hook="結論先出し", completion=0.7)
    rows = db.query_axis_performance("hook_type", metric="avg_completion")
    by_value = {r["axis_value"]: r for r in rows}
    assert "共感型" in by_value
    assert "結論先出し" in by_value
    assert by_value["共感型"]["metric"] == pytest.approx(0.45)
    assert by_value["結論先出し"]["metric"] == pytest.approx(0.7)


def test_query_axis_performance_excludes_within_24h(isolated_db):
    """投稿後 24h 経っていないものは v_axis_performance に乗らない。"""
    db = isolated_db
    _seed_chain(db, ts="recent", hook="新軸", completion=0.9, posted_days_ago=0)
    rows = db.query_axis_performance("hook_type")
    assert all(r["axis_value"] != "新軸" for r in rows)


def test_query_axis_performance_rejects_unknown_axis(isolated_db):
    with pytest.raises(ValueError):
        isolated_db.query_axis_performance("not_a_axis")


def test_query_axis_performance_rejects_unknown_metric(isolated_db):
    with pytest.raises(ValueError):
        isolated_db.query_axis_performance("hook_type", metric="bogus")


def test_query_axis_performance_aggregates_across_other_axes(isolated_db):
    """同じ hook_type が tone / emotion / theme 違いで複数 row を持っても、
    軸別 view は hook_type だけで GROUP BY するので 1 行に集約される。

    旧 v_axis_performance は 4 軸同時 GROUP BY だったため、(共感型, casual, ...) と
    (共感型, formal, ...) が別 row になり、bandit 側で重複扱いされていた。
    """
    db = isolated_db
    _seed_chain(db, ts="t1", hook="共感型", completion=0.4, tone="casual")
    _seed_chain(db, ts="t2", hook="共感型", completion=0.6, tone="formal")
    _seed_chain(db, ts="t3", hook="共感型", completion=0.8, tone="serious")
    rows = db.query_axis_performance("hook_type", metric="avg_completion")
    common = [r for r in rows if r["axis_value"] == "共感型"]
    assert len(common) == 1
    assert common[0]["n"] == 3
    assert common[0]["metric"] == pytest.approx(0.6)


def test_query_axis_performance_dispatches_per_axis(isolated_db):
    """各軸で独立した view が呼ばれることを 4 軸全部で確認。"""
    db = isolated_db
    _seed_chain(db, ts="a1", hook="共感型", completion=0.3,
                tone="casual", dominant_emotion="喜び", theme="career_change")
    _seed_chain(db, ts="a2", hook="結論先出し", completion=0.7,
                tone="serious", dominant_emotion="焦り", theme="salary")
    for axis, expected in (
        ("hook_type", {"共感型", "結論先出し"}),
        ("tone", {"casual", "serious"}),
        ("dominant_emotion", {"喜び", "焦り"}),
        ("theme", {"career_change", "salary"}),
    ):
        rows = db.query_axis_performance(axis)
        assert {r["axis_value"] for r in rows} == expected, axis
