"""Phase X-1: schema v8 + experiment_assignments 拡張のテスト。"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def test_schema_version_is_8(isolated_db):
    with isolated_db.get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()
    assert row["v"] == 8


def test_experiment_assignments_has_phase_x1_columns(isolated_db):
    with isolated_db.get_connection() as conn:
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(experiment_assignments)"
        )}
    assert "scene_idx" in cols
    assert "composition_id" in cols
    assert "composition_version" in cols


def test_insert_experiment_assignment_with_scene_idx(isolated_db):
    rid = isolated_db.insert_experiment_assignment(
        video_id="ts1", axis="hook_type",
        selected_value="共感型", strategy="shadow_explore",
        scene_idx=2,
        composition_id="abcd1234abcd1234",
        composition_version="v1",
    )
    assert rid > 0
    rows = isolated_db.list_experiment_assignments(video_id="ts1")
    assert len(rows) == 1
    assert rows[0]["scene_idx"] == 2
    assert rows[0]["composition_id"] == "abcd1234abcd1234"
    assert rows[0]["composition_version"] == "v1"


def test_insert_experiment_assignment_back_compat_without_scene_idx(isolated_db):
    """scene_idx 等を渡さない既存呼び出しは NULL で記録される (= back-compat)。"""
    rid = isolated_db.insert_experiment_assignment(
        video_id="ts1", axis="hook_type",
        selected_value="x", strategy="active_exploit",
    )
    assert rid > 0
    rows = isolated_db.list_experiment_assignments(video_id="ts1")
    assert len(rows) == 1
    assert rows[0]["scene_idx"] is None
    assert rows[0]["composition_id"] is None
    assert rows[0]["composition_version"] is None


def test_init_db_idempotent(isolated_db):
    """init_db を再呼び出ししても v8 列が壊れない (= ALTER TABLE 経路の確認)。"""
    from analytics import db as _db
    _db.init_db()
    _db.init_db()
    with _db.get_connection() as conn:
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(experiment_assignments)"
        )}
    assert "scene_idx" in cols
    assert "composition_id" in cols
    assert "composition_version" in cols
