import json
from pathlib import Path

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


@pytest.fixture
def sample_screenplay_file(tmp_path) -> str:
    sp = {
        "caption": "テスト",
        "scenes": [
            {
                "duration": 5.0,
                "background_prompt": "bg",
                "lines": [
                    {"text": "a", "start": 0.0, "end": 1.0, "emotion": "驚き"},
                    {"text": "b", "start": 1.0, "end": 3.0, "emotion": "喜び"},
                ],
            },
            {
                "duration": 3.0,
                "background_prompt": "bg2",
                "lines": [{"text": "c", "start": 0.0, "end": 2.0}],
            },
        ],
    }
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(sp, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_init_db_creates_tables(isolated_db) -> None:
    with isolated_db.get_connection() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert {"screenplays", "videos", "posts", "post_metrics", "schema_version"} <= tables


def test_upsert_screenplay_inserts_metadata(isolated_db, sample_screenplay_file) -> None:
    sp_id = isolated_db.upsert_screenplay(sample_screenplay_file)
    assert len(sp_id) == 12

    screenplays = isolated_db.list_screenplays()
    assert len(screenplays) == 1
    assert screenplays[0]["scene_count"] == 2
    assert screenplays[0]["line_count"] == 3
    assert screenplays[0]["total_duration"] == 8.0
    assert screenplays[0]["audio_mode"] is None


def test_upsert_screenplay_idempotent(isolated_db, sample_screenplay_file) -> None:
    id1 = isolated_db.upsert_screenplay(sample_screenplay_file)
    id2 = isolated_db.upsert_screenplay(sample_screenplay_file)
    assert id1 == id2
    assert len(isolated_db.list_screenplays()) == 1


def test_update_screenplay_tags(isolated_db, sample_screenplay_file) -> None:
    sp_id = isolated_db.upsert_screenplay(sample_screenplay_file)
    isolated_db.update_screenplay_tags(sp_id, {
        "hook_type": "timeline",
        "tone": "casual",
        "dominant_emotion": "喜び",
        "theme": "career_change",
        "character_archetype": "若い女性エンジニア",
    })
    rows = isolated_db.list_screenplays()
    assert rows[0]["hook_type"] == "timeline"
    assert rows[0]["theme"] == "career_change"


def test_insert_video_and_link(isolated_db, sample_screenplay_file) -> None:
    sp_id = isolated_db.upsert_screenplay(sample_screenplay_file)
    isolated_db.insert_video("20260425_120000", sp_id, "/tmp/reels.mp4",
                             duration_sec=51.0, generation_cost_usd=18.3)

    with isolated_db.get_connection() as conn:
        row = conn.execute("SELECT * FROM videos").fetchone()
    assert row["id"] == "20260425_120000"
    assert row["screenplay_id"] == sp_id
    assert row["duration_sec"] == 51.0


def test_register_post_and_insert_metrics(isolated_db, sample_screenplay_file) -> None:
    sp_id = isolated_db.upsert_screenplay(sample_screenplay_file)
    isolated_db.insert_video("v1", sp_id, "/tmp/v1.mp4")
    post_id = isolated_db.register_post("v1", "youtube", "abc123",
                                        url="https://youtube.com/watch?v=abc123")
    assert post_id == "youtube:abc123"

    isolated_db.insert_metrics(post_id, {
        "views": 1000, "likes": 50, "comments": 5, "shares": 2,
        "completion_rate": 0.72, "raw_response": {"k": "v"},
    })

    perf = isolated_db.query_performance()
    assert len(perf) == 1
    assert perf[0]["views"] == 1000
    assert perf[0]["platform"] == "youtube"


def test_query_performance_without_metrics(isolated_db, sample_screenplay_file) -> None:
    sp_id = isolated_db.upsert_screenplay(sample_screenplay_file)
    isolated_db.insert_video("v2", sp_id, "/tmp/v2.mp4")
    perf = isolated_db.query_performance()
    assert len(perf) == 1
    assert perf[0]["views"] is None


def test_register_post_rejects_invalid_platform(isolated_db, sample_screenplay_file) -> None:
    sp_id = isolated_db.upsert_screenplay(sample_screenplay_file)
    isolated_db.insert_video("v3", sp_id, "/tmp/v3.mp4")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        isolated_db.register_post("v3", "mixi", "xxx")
