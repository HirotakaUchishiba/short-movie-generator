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


def test_insert_video_with_final_metadata(isolated_db, sample_screenplay_file) -> None:
    sp_id = isolated_db.upsert_screenplay(sample_screenplay_file)
    isolated_db.insert_video(
        "v_final", sp_id, "/tmp/final.mp4",
        duration_sec=28.5, generation_cost_usd=15.0,
        final_imported=True, final_filename="142233.mp4",
        final_audio_match_score=0.87,
    )
    with isolated_db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE id = 'v_final'"
        ).fetchone()
    assert row["final_imported"] == 1
    assert row["final_filename"] == "142233.mp4"
    assert row["final_audio_match_score"] == 0.87


def test_append_stage_run_creates_record(isolated_db) -> None:
    isolated_db.append_stage_run(
        ts="20260507_120000", stage="script",
        started_at="2026-05-07T12:00:00", ended_at="2026-05-07T12:00:01",
        status="completed",
    )
    rec = isolated_db.get_generation_record("20260507_120000")
    assert rec is not None
    assert rec["status"] == "in_progress"  # stage append では status は触らない
    runs = json.loads(rec["stage_runs"])
    assert len(runs) == 1
    assert runs[0]["stage"] == "script"
    assert runs[0]["status"] == "completed"


def test_append_stage_run_accumulates_cost(isolated_db) -> None:
    isolated_db.append_stage_run(
        ts="20260507_130000", stage="bg",
        started_at="2026-05-07T13:00:00", ended_at="2026-05-07T13:00:10",
        status="completed", cost_usd=1.5,
    )
    isolated_db.append_stage_run(
        ts="20260507_130000", stage="kling",
        started_at="2026-05-07T13:00:11", ended_at="2026-05-07T13:00:30",
        status="completed", cost_usd=3.36,
    )
    rec = isolated_db.get_generation_record("20260507_130000")
    runs = json.loads(rec["stage_runs"])
    assert len(runs) == 2
    assert rec["total_cost_usd"] == pytest.approx(4.86, rel=1e-3)


def test_append_stage_run_extra_metadata(isolated_db) -> None:
    isolated_db.append_stage_run(
        ts="20260507_131500", stage="kling",
        started_at="x", ended_at="y", status="failed",
        retry_count=2, extra={"error": "timeout"},
    )
    runs = json.loads(isolated_db.get_generation_record(
        "20260507_131500")["stage_runs"])
    assert runs[0]["retry_count"] == 2
    assert runs[0]["error"] == "timeout"


def test_update_generation_record_partial(isolated_db, sample_screenplay_file) -> None:
    sp_id = isolated_db.upsert_screenplay(sample_screenplay_file)
    isolated_db.insert_video("vid_abc", sp_id, "/tmp/v.mp4")
    isolated_db.append_stage_run(
        ts="20260507_140000", stage="script",
        started_at="x", ended_at="y", status="completed",
    )
    isolated_db.update_generation_record(
        "20260507_140000",
        video_id="vid_abc",
        prompts={"bg": [{"scene_idx": 0, "prompt": "p0"}]},
        status="completed",
    )
    rec = isolated_db.get_generation_record("20260507_140000")
    assert rec["video_id"] == "vid_abc"
    assert rec["status"] == "completed"
    assert json.loads(rec["prompts"])["bg"][0]["scene_idx"] == 0


def test_update_generation_record_creates_missing_row(isolated_db) -> None:
    isolated_db.update_generation_record(
        "20260507_150000",
        screenplay_sha="abcd",
    )
    rec = isolated_db.get_generation_record("20260507_150000")
    assert rec is not None
    assert rec["screenplay_sha"] == "abcd"


def test_update_generation_record_rejects_unknown_field(isolated_db) -> None:
    with pytest.raises(ValueError):
        isolated_db.update_generation_record(
            "20260507_160000", _no_such_field="x",
        )


def test_insert_and_list_qa_failures(isolated_db) -> None:
    fid1 = isolated_db.insert_qa_failure(
        ts="20260507_120000", stage="bg", source="human_reject",
        tags=["character_drift"], note="顔が崩れた",
        scene_idx=2, artifact_path="/tmp/bg_2.png",
    )
    fid2 = isolated_db.insert_qa_failure(
        ts="20260507_120000", stage="tts", source="auto_flagged",
        tags=["audio_silence"], scene_idx=1, line_idx=0,
    )
    assert fid1 != fid2

    rows = isolated_db.list_qa_failures(ts="20260507_120000")
    assert len(rows) == 2
    bg_row = next(r for r in rows if r["stage"] == "bg")
    assert bg_row["tags"] == ["character_drift"]
    assert bg_row["note"] == "顔が崩れた"

    bg_only = isolated_db.list_qa_failures(stage="bg")
    assert len(bg_only) == 1

    auto_only = isolated_db.list_qa_failures(source="auto_flagged")
    assert len(auto_only) == 1


def test_count_qa_failures(isolated_db) -> None:
    isolated_db.insert_qa_failure(ts="t1", stage="tts", source="human_reject", tags=[])
    isolated_db.insert_qa_failure(ts="t1", stage="bg", source="human_reject", tags=[])
    isolated_db.insert_qa_failure(ts="t1", stage="bg", source="regenerate_implicit", tags=[])

    assert isolated_db.count_qa_failures() == 3
    assert isolated_db.count_qa_failures(stage="bg") == 2
    assert isolated_db.count_qa_failures(source="human_reject") == 2


def test_reference_videos_has_license_columns(isolated_db) -> None:
    with isolated_db.get_connection() as conn:
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(reference_videos)"
        )}
    assert {"source_url", "fetched_at", "license_status"} <= cols


def test_init_db_adds_license_columns_to_existing(tmp_path, monkeypatch) -> None:
    """schema v4 以前で作られた reference_videos に source_url 等が後から ALTER で
    追加されることを確認 (= 既存運用 DB を壊さない)。"""
    import sqlite3
    db_path = tmp_path / "old_v4.db"
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE reference_videos (
            sha256 TEXT PRIMARY KEY,
            original_name TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            duration_sec REAL,
            uploaded_at TEXT NOT NULL,
            last_used_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    from analytics import db as _db
    _db.init_db()
    with _db.get_connection() as conn:
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(reference_videos)"
        )}
    assert {"source_url", "fetched_at", "license_status"} <= cols


def test_init_db_migrates_old_videos_table(tmp_path, monkeypatch) -> None:
    """schema_version 3 以前で作られた videos テーブル (final_* カラム無し) に
    init_db が ALTER TABLE で追加できることを確認。"""
    import sqlite3
    db_path = tmp_path / "old.db"
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE videos (
            id TEXT PRIMARY KEY,
            screenplay_id TEXT NOT NULL,
            output_path TEXT NOT NULL,
            duration_sec REAL,
            generation_cost_usd REAL,
            generated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    from analytics import db as _db
    _db.init_db()
    with _db.get_connection() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(videos)")}
    assert {"final_imported", "final_filename", "final_audio_match_score"} <= cols
