"""analytics/db.py の schema migration テスト。

旧バージョンの DB ファイル (= 一部 column が無い state) を作成し、
init_db() が _ensure_column 経由で additive migration を正しく走らせる
ことを検証する。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §4.4
"""

import sqlite3

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """test 用に DB path を tmp_path に向ける。init_db は test ごとに呼ぶ。"""
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    return _db


def _create_old_schema_posts_table(db_path: str) -> None:
    """rollback_at / rollback_reason が無い旧 schema の posts table を作る。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """CREATE TABLE posts (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                platform_post_id TEXT NOT NULL,
                url TEXT,
                posted_at TEXT,
                caption TEXT,
                hashtags TEXT,
                registered_at TEXT
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def test_init_db_adds_rollback_columns_to_existing_posts_table(
    isolated_db, tmp_path,
):
    """旧 posts table (= rollback_at 無し) に init_db すると additive で追加される。"""
    db_path = str(tmp_path / "analytics.db")
    _create_old_schema_posts_table(db_path)

    isolated_db.init_db()

    with isolated_db.get_connection() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(posts)")}
    assert "rollback_at" in cols
    assert "rollback_reason" in cols


def test_init_db_adds_v10_traffic_columns_to_post_metrics(isolated_db):
    """v10 で追加された traffic_*_pct 6 列が新規 DB でも揃う。"""
    isolated_db.init_db()
    with isolated_db.get_connection() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(post_metrics)")}
    assert "impressions" in cols
    assert "subscribers_gained" in cols
    assert "traffic_browse_pct" in cols
    assert "traffic_suggested_pct" in cols
    assert "traffic_search_pct" in cols
    assert "traffic_external_pct" in cols


def test_init_db_adds_v11_screenplay_columns(isolated_db):
    """v11 で追加された transformation / tree_main_branch / pov_id が揃う。"""
    isolated_db.init_db()
    with isolated_db.get_connection() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(screenplays)")}
    assert "transformation" in cols
    assert "tree_main_branch" in cols
    assert "pov_id" in cols


def test_init_db_records_current_schema_version(isolated_db):
    """init_db 後に schema_version table に CURRENT_SCHEMA_VERSION が記録される。"""
    isolated_db.init_db()
    with isolated_db.get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()
    assert row["v"] == isolated_db.CURRENT_SCHEMA_VERSION


def test_init_db_idempotent_no_duplicate_version_records(isolated_db):
    """init_db を 2 回呼んでも schema_version の現行行は 1 度しか追加されない。"""
    isolated_db.init_db()
    isolated_db.init_db()
    with isolated_db.get_connection() as conn:
        rows = conn.execute(
            "SELECT version FROM schema_version "
            "WHERE version = ?",
            (isolated_db.CURRENT_SCHEMA_VERSION,),
        ).fetchall()
    # 同じバージョンが 1 度だけ記録される (= idempotent)
    assert len(rows) == 1


def test_init_db_recreates_active_posts_view_with_rollback_filter(isolated_db):
    """v9 で導入された v_active_posts は rollback_at IS NULL の post だけを返す。"""
    isolated_db.init_db()
    with isolated_db.get_connection() as conn:
        view_def = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name='v_active_posts'"
        ).fetchone()
    assert view_def is not None
    assert "rollback_at" in view_def["sql"]
