"""Phase 3.5 / 4.5: v_strategy_performance view と strategy 別 reward 集計のテスト。"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def _seed_video_with_post(db, *, video_id: str, sp_id: str = "sp1",
                          platform: str = "youtube",
                          platform_post_id: str = "yt_x",
                          posted_days_ago: int = 2,
                          metric_completion: float = 0.5):
    """screenplay → video → post → metric を 1 セット仕込む。"""
    post_id = f"{platform}:{platform_post_id}"
    with db.get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO screenplays (id, path, name, sha256,
               created_at, raw_json)
               VALUES (?, '/x', 'x', ?, datetime('now', '-10 days'), '{}')""",
            (sp_id, sp_id),
        )
        conn.execute(
            """INSERT OR IGNORE INTO videos (id, screenplay_id, output_path,
               generated_at)
               VALUES (?, ?, '/tmp/v.mp4', datetime('now', '-' || ? || ' days'))""",
            (video_id, sp_id, posted_days_ago + 1),
        )
        conn.execute(
            """INSERT OR REPLACE INTO posts (id, video_id, platform,
               platform_post_id, url, posted_at, registered_at)
               VALUES (?, ?, ?, ?, ?,
                       datetime('now', '-' || ? || ' days'),
                       datetime('now'))""",
            (post_id, video_id, platform, platform_post_id,
             f"https://x/{platform_post_id}", posted_days_ago),
        )
        conn.execute(
            """INSERT INTO post_metrics(post_id, fetched_at, views,
               completion_rate, saves)
               VALUES (?, datetime('now'), 100, ?, 5)""",
            (post_id, metric_completion),
        )
    return post_id


def _seed_assignment(db, *, video_id: str, axis: str, value: str,
                     strategy: str):
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO experiment_assignments
               (video_id, axis, selected_value, strategy, created_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (video_id, axis, value, strategy),
        )


def test_v_strategy_performance_separates_active_and_shadow(isolated):
    db = isolated
    # active で video1 を試す → completion 0.8
    _seed_video_with_post(db, video_id="v_active",
                          platform_post_id="yt_a",
                          metric_completion=0.8)
    _seed_assignment(db, video_id="v_active", axis="hook_type",
                     value="problem_setup", strategy="active_explore")
    # shadow で video2 を試す → completion 0.4
    _seed_video_with_post(db, video_id="v_shadow",
                          platform_post_id="yt_s",
                          metric_completion=0.4)
    _seed_assignment(db, video_id="v_shadow", axis="hook_type",
                     value="problem_setup", strategy="shadow_explore")

    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT strategy, axis, selected_value, n, avg_completion "
            "FROM v_strategy_performance ORDER BY strategy"
        ).fetchall()
    by_strategy = {r["strategy"]: dict(r) for r in rows}
    assert "active_explore" in by_strategy
    assert "shadow_explore" in by_strategy
    assert by_strategy["active_explore"]["avg_completion"] == pytest.approx(0.8)
    assert by_strategy["shadow_explore"]["avg_completion"] == pytest.approx(0.4)


def test_query_axis_performance_filters_by_strategy_prefix(isolated):
    db = isolated
    _seed_video_with_post(db, video_id="vA",
                          platform_post_id="yt_aa",
                          metric_completion=0.9)
    _seed_assignment(db, video_id="vA", axis="hook_type",
                     value="problem_setup", strategy="active_explore")
    _seed_video_with_post(db, video_id="vS",
                          platform_post_id="yt_ss",
                          metric_completion=0.3)
    _seed_assignment(db, video_id="vS", axis="hook_type",
                     value="problem_setup", strategy="shadow_explore")

    active = db.query_axis_performance(
        "hook_type", strategy_prefix="active",
    )
    shadow = db.query_axis_performance(
        "hook_type", strategy_prefix="shadow",
    )
    assert len(active) == 1 and active[0]["metric"] == pytest.approx(0.9)
    assert len(shadow) == 1 and shadow[0]["metric"] == pytest.approx(0.3)


def test_v_strategy_performance_excludes_rolled_back_posts(isolated):
    db = isolated
    post_id = _seed_video_with_post(
        db, video_id="v_rb", platform_post_id="yt_rb",
        metric_completion=0.7,
    )
    _seed_assignment(db, video_id="v_rb", axis="hook_type",
                     value="problem_setup", strategy="active_explore")
    # rollback すると v_active_posts から消える → v_strategy_performance も空
    db.mark_post_rolled_back(post_id, reason="test")
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM v_strategy_performance"
        ).fetchall()
    assert len(rows) == 0


# NOTE: improvement.axis_performance に strategy_prefix を流す高レイヤテストは
# 後続 PR (= operations-roadmap branch) で test_axis_performance_strategy.py として追加する。
# ここでは DB レイヤ (= v_strategy_performance view + db.query_axis_performance(strategy_prefix=...))
# のみカバーする。
