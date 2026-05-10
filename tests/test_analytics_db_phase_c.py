"""Phase C: schema v11 (= screenplays に transformation/tree_main_branch/pov_id) +
v_transformation_performance / v_halo_effect のテスト。"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def _seed_chain(db, *, ts: str,
                transformation: str | None = None,
                tree_main_branch: str | None = None,
                pov_id: str | None = None,
                views: int = 1000,
                completion: float = 0.5,
                subs_gained: int = 5,
                posted_days_ago: int = 2):
    sp_id = f"sp_{ts}"
    v_id = f"v_{ts}"
    p_id = f"p_{ts}"
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO screenplays (id, path, name, sha256, created_at, raw_json, "
            "transformation, tree_main_branch, pov_id) "
            "VALUES (?, '/x', 'x', ?, datetime('now'), '{}', ?, ?, ?)",
            (sp_id, sp_id + "_sha", transformation, tree_main_branch, pov_id),
        )
        conn.execute(
            "INSERT INTO videos (id, screenplay_id, output_path, generated_at) "
            "VALUES (?, ?, '/x', datetime('now'))",
            (v_id, sp_id),
        )
        conn.execute(
            "INSERT INTO posts (id, video_id, platform, platform_post_id, "
            "posted_at, registered_at) "
            "VALUES (?, ?, 'youtube', ?, "
            "datetime('now', '-' || ? || ' days'), datetime('now'))",
            (p_id, v_id, p_id, posted_days_ago),
        )
        conn.execute(
            "INSERT INTO post_metrics (post_id, fetched_at, views, "
            "completion_rate, subscribers_gained) "
            "VALUES (?, datetime('now'), ?, ?, ?)",
            (p_id, views, completion, subs_gained),
        )


# ───────────── schema v11 columns ─────────────

def test_screenplays_has_v11_columns(isolated_db):
    db = isolated_db
    with db.get_connection() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(screenplays)")}
    for c in ("transformation", "tree_main_branch", "pov_id"):
        assert c in cols, f"v11 列 {c} が screenplays に追加されていない"


def test_update_screenplay_tags_writes_v11_fields(isolated_db):
    db = isolated_db
    sp_id = "sp_x"
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO screenplays (id, path, name, sha256, created_at, raw_json) "
            "VALUES (?, '/x', 'x', 'sha_x', datetime('now'), '{}')",
            (sp_id,),
        )
    db.update_screenplay_tags(sp_id, {
        "hook_type": "tips",
        "tone": "informative",
        "dominant_emotion": "中立",
        "theme": "skills",
        "character_archetype": "若手エンジニア",
        "transformation": "skill_acquisition",
        "tree_main_branch": "how_to_solve",
        "pov_id": "practical",
    })
    rows = db.list_screenplays()
    row = next(r for r in rows if r["id"] == sp_id)
    assert row["transformation"] == "skill_acquisition"
    assert row["tree_main_branch"] == "how_to_solve"
    assert row["pov_id"] == "practical"


def test_update_screenplay_tags_preserves_existing_v11_when_omitted(isolated_db):
    """tags dict に v11 フィールドが無い場合、既存値を消さない (= COALESCE で保護)。"""
    db = isolated_db
    sp_id = "sp_keep"
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO screenplays (id, path, name, sha256, created_at, "
            "raw_json, transformation, tree_main_branch, pov_id) "
            "VALUES (?, '/x', 'x', 'sha_keep', datetime('now'), '{}', "
            "'salary_up', 'how_to_solve', 'data_driven')",
            (sp_id,),
        )
    db.update_screenplay_tags(sp_id, {
        "hook_type": "tips",
        "tone": "informative",
        "dominant_emotion": "中立",
        "theme": "salary",
        "character_archetype": "x",
    })
    row = next(r for r in db.list_screenplays() if r["id"] == sp_id)
    # v11 フィールドは触らない指定 → 既存値が残る
    assert row["transformation"] == "salary_up"
    assert row["tree_main_branch"] == "how_to_solve"
    assert row["pov_id"] == "data_driven"


# ───────────── v_transformation_performance ─────────────

def test_query_transformation_performance_groups_by_pair(isolated_db):
    db = isolated_db
    _seed_chain(db, ts="t1", transformation="career_pivot",
                tree_main_branch="problem_diagnosis",
                views=1000, completion=0.5)
    _seed_chain(db, ts="t2", transformation="career_pivot",
                tree_main_branch="how_to_solve",
                views=2000, completion=0.7)
    _seed_chain(db, ts="t3", transformation="salary_up",
                tree_main_branch="how_to_solve",
                views=500, completion=0.3)
    rows = db.query_transformation_performance()
    pairs = {(r["transformation"], r["tree_main_branch"]) for r in rows}
    assert ("career_pivot", "problem_diagnosis") in pairs
    assert ("career_pivot", "how_to_solve") in pairs
    assert ("salary_up", "how_to_solve") in pairs


def test_query_transformation_performance_excludes_null_transformation(isolated_db):
    db = isolated_db
    _seed_chain(db, ts="tagged", transformation="career_pivot",
                tree_main_branch="how_to_solve")
    _seed_chain(db, ts="untagged", transformation=None,
                tree_main_branch=None)
    rows = db.query_transformation_performance()
    assert len(rows) == 1
    assert rows[0]["transformation"] == "career_pivot"


def test_query_transformation_performance_filters_by_24h(isolated_db):
    """投稿後 24h 未満の動画は v_transformation_performance に出ない。"""
    db = isolated_db
    _seed_chain(db, ts="fresh", transformation="career_pivot",
                tree_main_branch="how_to_solve", posted_days_ago=0)
    rows = db.query_transformation_performance()
    assert rows == []


# ───────────── v_halo_effect ─────────────

def test_query_halo_effect_aggregates_per_transformation(isolated_db):
    db = isolated_db
    _seed_chain(db, ts="cp1", transformation="career_pivot", views=1000, subs_gained=10)
    _seed_chain(db, ts="cp2", transformation="career_pivot", views=10000, subs_gained=200)
    _seed_chain(db, ts="su1", transformation="salary_up", views=500, subs_gained=2)

    rows = db.query_halo_effect()
    by_t = {r["transformation"]: r for r in rows}

    assert "career_pivot" in by_t
    assert by_t["career_pivot"]["n_posts"] == 2
    assert by_t["career_pivot"]["peak_views"] == 10000
    assert by_t["career_pivot"]["avg_views"] == pytest.approx(5500)
    assert by_t["career_pivot"]["total_subs_gained"] == 210


def test_query_halo_effect_excludes_null_transformation(isolated_db):
    db = isolated_db
    _seed_chain(db, ts="t1", transformation=None)
    rows = db.query_halo_effect()
    assert rows == []
