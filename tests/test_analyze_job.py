"""analyze.job の単体テスト (SQLite ジョブ永続化 + 状態機械)。"""
import json

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def test_create_and_get_job_initializes_phases(isolated_db) -> None:
    from analyze.job import create_job, get_job, get_phases, PHASES

    j = create_job("sha_abc", {"fps": 2.0, "no_shots": False})
    assert j.id.startswith("analyze_")
    assert j.video_sha256 == "sha_abc"
    assert j.status == "pending"
    assert json.loads(j.options_json)["fps"] == 2.0

    got = get_job(j.id)
    assert got.id == j.id

    phases = get_phases(j.id)
    assert {p["phase"] for p in phases} == set(PHASES)
    for p in phases:
        assert p["status"] == "pending"
        assert p["started_at"] is None


def test_get_job_raises_for_unknown(isolated_db) -> None:
    from analyze.job import get_job

    with pytest.raises(KeyError):
        get_job("nonexistent")


def test_transition_status_sets_timestamps(isolated_db) -> None:
    from analyze.job import create_job, transition_status

    j = create_job("sha", {})
    j2 = transition_status(j.id, "running")
    assert j2.status == "running"
    assert j2.started_at is not None
    assert j2.finished_at is None

    j3 = transition_status(j.id, "completed",
                            screenplay_path="/tmp/x.json",
                            actual_cost_usd=0.42)
    assert j3.status == "completed"
    assert j3.finished_at is not None
    assert j3.screenplay_path == "/tmp/x.json"
    assert j3.actual_cost_usd == 0.42


def test_transition_status_rejects_unknown(isolated_db) -> None:
    from analyze.job import create_job, transition_status

    j = create_job("sha", {})
    with pytest.raises(ValueError):
        transition_status(j.id, "weird_status")


def test_dryrun_flow_status_transitions(isolated_db) -> None:
    from analyze.job import create_job, transition_status

    j = create_job("sha", {})
    j = transition_status(j.id, "dryrunning")
    assert j.status == "dryrunning"
    j = transition_status(j.id, "awaiting_confirm",
                           estimated_cost_usd=0.30)
    assert j.status == "awaiting_confirm"
    assert j.estimated_cost_usd == 0.30
    j = transition_status(j.id, "running")
    assert j.status == "running"


def test_phase_lifecycle(isolated_db) -> None:
    from analyze.job import (create_job, start_phase, complete_phase,
                              fail_phase, skip_phase, get_phases, get_job)

    j = create_job("sha", {})
    start_phase(j.id, "frames")
    complete_phase(j.id, "frames", duration_ms=1234, cost_usd=0.0)
    start_phase(j.id, "claude")
    fail_phase(j.id, "claude", "rate limit")
    skip_phase(j.id, "shots")

    rows = {p["phase"]: p for p in get_phases(j.id)}
    assert rows["frames"]["status"] == "completed"
    assert rows["frames"]["duration_ms"] == 1234
    assert rows["claude"]["status"] == "failed"
    assert rows["claude"]["error"] == "rate limit"
    assert rows["shots"]["status"] == "skipped"

    # current_phase が start_phase で更新される
    assert get_job(j.id).current_phase == "claude"


def test_cancellation_request(isolated_db) -> None:
    from analyze.job import (create_job, request_cancellation,
                              is_cancellation_requested)

    j = create_job("sha", {})
    assert not is_cancellation_requested(j.id)
    request_cancellation(j.id)
    assert is_cancellation_requested(j.id)


def test_list_jobs_orders_by_created_desc(isolated_db) -> None:
    import time
    from analyze.job import create_job, list_jobs

    j1 = create_job("sha1", {})
    time.sleep(0.01)
    j2 = create_job("sha2", {})

    items = list_jobs()
    assert items[0].id == j2.id
    assert items[1].id == j1.id


def test_options_property_parses_json(isolated_db) -> None:
    from analyze.job import create_job

    j = create_job("sha", {"fps": 1.5, "no_shots": True})
    assert j.options == {"fps": 1.5, "no_shots": True}


# ─── reference_videos ───────────────────────────────────────────


def test_upsert_reference_video_inserts_then_touches(isolated_db) -> None:
    from analyze.job import upsert_reference_video, get_reference_video

    upsert_reference_video("sha1", original_name="a.mov",
                            size_bytes=1234, duration_sec=10.5)
    r = get_reference_video("sha1")
    assert r["original_name"] == "a.mov"
    assert r["size_bytes"] == 1234
    assert r["duration_sec"] == 10.5
    first_uploaded = r["uploaded_at"]
    assert r["last_used_at"] is None

    # 2回目: メタデータは変えず last_used_at だけ更新
    upsert_reference_video("sha1", original_name="ignored.mov",
                            size_bytes=9999)
    r2 = get_reference_video("sha1")
    assert r2["original_name"] == "a.mov"  # 元のまま
    assert r2["uploaded_at"] == first_uploaded
    assert r2["last_used_at"] is not None


def test_list_reference_videos_returns_all(isolated_db) -> None:
    """順序は uploaded_at DESC で SQL 句が指定済み (秒単位精度のため厳密検証はしない)。"""
    from analyze.job import upsert_reference_video, list_reference_videos

    upsert_reference_video("sha1", original_name="a.mov", size_bytes=1)
    upsert_reference_video("sha2", original_name="b.mov", size_bytes=2)

    items = list_reference_videos()
    shas = {it["sha256"] for it in items}
    assert shas == {"sha1", "sha2"}
    assert len(items) == 2


def test_delete_reference_video_blocked_by_job(isolated_db) -> None:
    from analyze.job import (upsert_reference_video, delete_reference_video,
                              create_job, get_reference_video)

    upsert_reference_video("sha_used", original_name="x.mov", size_bytes=1)
    upsert_reference_video("sha_unused", original_name="y.mov", size_bytes=1)

    create_job("sha_used", {})

    assert delete_reference_video("sha_unused") is True
    assert get_reference_video("sha_unused") is None

    assert delete_reference_video("sha_used") is False
    assert get_reference_video("sha_used") is not None
