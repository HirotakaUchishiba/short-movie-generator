"""Phase 3: experiment_assignments.observed_value back-fill のテスト。"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def _seed_screenplay_video(db, *, ts: str, sp_id: str,
                           hook="共感型", tone="casual",
                           emotion="喜び", theme="career_change"):
    """ts (= videos.id) で 1 screenplay + 1 video を挿入。"""
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO screenplays (id, path, name, sha256, created_at,
               raw_json, hook_type, tone, dominant_emotion, theme)
               VALUES (?, '/x', 'x', ?, datetime('now'), '{}', ?, ?, ?, ?)""",
            (sp_id, sp_id + "_sha", hook, tone, emotion, theme),
        )
        conn.execute(
            """INSERT INTO videos (id, screenplay_id, output_path, generated_at)
               VALUES (?, ?, '/x', datetime('now'))""",
            (ts, sp_id),
        )


def test_back_fill_observed_for_ts_writes_from_screenplays(isolated_db):
    db = isolated_db
    db.insert_experiment_assignment(
        video_id="ts1", axis="hook_type",
        selected_value="結論先出し", strategy="active_explore",
    )
    _seed_screenplay_video(db, ts="ts1", sp_id="sp1", hook="共感型")

    from improvement.observed import back_fill_observed_for_ts
    n = back_fill_observed_for_ts("ts1")
    assert n == 1
    rows = db.list_experiment_assignments(video_id="ts1")
    assert rows[0]["observed_value"] == "共感型"
    assert rows[0]["selected_value"] == "結論先出し"


def test_back_fill_observed_skips_when_video_not_yet_ingested(isolated_db):
    """ingest_video が走る前は videos に row が無いので NULL のまま。"""
    db = isolated_db
    db.insert_experiment_assignment(
        video_id="ts2", axis="tone",
        selected_value="serious", strategy="shadow_explore",
    )
    from improvement.observed import back_fill_observed_for_ts
    n = back_fill_observed_for_ts("ts2")
    assert n == 0
    rows = db.list_experiment_assignments(video_id="ts2")
    assert rows[0]["observed_value"] is None


def test_back_fill_observed_skips_when_axis_untagged(isolated_db):
    """auto_tag が走らず screenplays.<axis> が NULL なら更新しない。"""
    db = isolated_db
    db.insert_experiment_assignment(
        video_id="ts3", axis="theme",
        selected_value="salary", strategy="active_exploit",
    )
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO screenplays (id, path, name, sha256, created_at,
               raw_json) VALUES ('sp3', '/x', 'x', 'sp3_sha',
               datetime('now'), '{}')""",
        )
        conn.execute(
            """INSERT INTO videos (id, screenplay_id, output_path, generated_at)
               VALUES ('ts3', 'sp3', '/x', datetime('now'))""",
        )
    from improvement.observed import back_fill_observed_for_ts
    n = back_fill_observed_for_ts("ts3")
    assert n == 0
    rows = db.list_experiment_assignments(video_id="ts3")
    assert rows[0]["observed_value"] is None


def test_back_fill_observed_is_idempotent(isolated_db):
    """同じ ts を 2 回 back-fill しても結果は同じ。"""
    db = isolated_db
    db.insert_experiment_assignment(
        video_id="ts4", axis="hook_type",
        selected_value="結論先出し", strategy="active_explore",
    )
    _seed_screenplay_video(db, ts="ts4", sp_id="sp4", hook="共感型")
    from improvement.observed import back_fill_observed_for_ts
    n1 = back_fill_observed_for_ts("ts4")
    n2 = back_fill_observed_for_ts("ts4")
    assert n1 == 1
    # 2 回目も UPDATE 自体は走るが値は変わらない
    rows = db.list_experiment_assignments(video_id="ts4")
    assert rows[0]["observed_value"] == "共感型"
    # rowcount は SQLite の場合 UPDATE で値が同じでも 1 を返す
    assert n2 == 1


def test_back_fill_observed_updates_each_axis_independently(isolated_db):
    """4 軸の assignment を 1 video に書き、それぞれ別の observed が入る。"""
    db = isolated_db
    for axis, sel in (
        ("hook_type", "結論先出し"),
        ("tone", "serious"),
        ("dominant_emotion", "焦り"),
        ("theme", "salary"),
    ):
        db.insert_experiment_assignment(
            video_id="ts5", axis=axis,
            selected_value=sel, strategy="active_explore",
        )
    _seed_screenplay_video(
        db, ts="ts5", sp_id="sp5",
        hook="共感型", tone="casual", emotion="喜び", theme="career_change",
    )
    from improvement.observed import back_fill_observed_for_ts
    n = back_fill_observed_for_ts("ts5")
    assert n == 4
    rows = {r["axis"]: r["observed_value"]
            for r in db.list_experiment_assignments(video_id="ts5")}
    assert rows == {
        "hook_type": "共感型",
        "tone": "casual",
        "dominant_emotion": "喜び",
        "theme": "career_change",
    }


def test_back_fill_for_screenplay_walks_all_videos(isolated_db):
    """1 screenplay を複数 video が参照しているとき、全 video を back-fill する。"""
    db = isolated_db
    for ts in ("tsA", "tsB"):
        db.insert_experiment_assignment(
            video_id=ts, axis="hook_type",
            selected_value="結論先出し", strategy="active_explore",
        )
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO screenplays (id, path, name, sha256, created_at,
               raw_json, hook_type) VALUES ('sp6', '/x', 'x', 'sp6_sha',
               datetime('now'), '{}', '共感型')""",
        )
        for ts in ("tsA", "tsB"):
            conn.execute(
                """INSERT INTO videos (id, screenplay_id, output_path,
                   generated_at) VALUES (?, 'sp6', '/x', datetime('now'))""",
                (ts,),
            )
    from improvement.observed import back_fill_observed_for_screenplay
    n = back_fill_observed_for_screenplay("sp6")
    assert n == 2
    for ts in ("tsA", "tsB"):
        rows = db.list_experiment_assignments(video_id=ts)
        assert rows[0]["observed_value"] == "共感型"
