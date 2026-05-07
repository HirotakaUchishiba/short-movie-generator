"""job_store 永続化レイヤのテスト。"""

import json
import os

import pytest

import job_store


@pytest.fixture(autouse=True)
def _isolate_job_store(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_STORE_DIR", str(tmp_path))


def test_create_persists_running_record():
    rec = job_store.create("abc12345", kind="run-next", ts="20990101_000000")
    assert rec["id"] == "abc12345"
    assert rec["status"] == "running"
    on_disk = job_store.get("abc12345")
    assert on_disk is not None
    assert on_disk["status"] == "running"
    assert on_disk["finished_at"] is None


def test_update_writes_status_and_finished_at():
    job_store.create("abc12345", kind="regen-bg", ts="x")
    job_store.update("abc12345", status="completed")
    rec = job_store.get("abc12345")
    assert rec["status"] == "completed"
    assert rec["finished_at"] is not None


def test_update_failed_includes_error():
    job_store.create("err1", kind="regen-tts", ts="x")
    job_store.update("err1", status="failed", error="boom")
    rec = job_store.get("err1")
    assert rec["status"] == "failed"
    assert rec["error"] == "boom"
    assert rec["finished_at"] is not None


def test_update_unknown_returns_none():
    assert job_store.update("nope", status="completed") is None


def test_recover_lost_marks_running_as_lost():
    job_store.create("a", kind="x", ts="1")
    job_store.create("b", kind="x", ts="2")
    job_store.update("b", status="completed")

    affected = job_store.recover_lost()
    assert [r["id"] for r in affected] == ["a"]
    assert affected[0]["ts"] == "1"
    assert affected[0]["status"] == "lost"

    a = job_store.get("a")
    b = job_store.get("b")
    assert a["status"] == "lost"
    assert "preview_server" in (a.get("error") or "")
    assert b["status"] == "completed"


def test_recover_lost_idempotent():
    job_store.create("a", kind="x", ts="1")
    first = job_store.recover_lost()
    second = job_store.recover_lost()
    assert [r["id"] for r in first] == ["a"]
    assert second == []


def test_list_all_sorted_newest_first(monkeypatch):
    job_store.create("old", kind="x", ts="1", started_at=1.0)
    job_store.create("new", kind="x", ts="1", started_at=10.0)
    items = job_store.list_all()
    assert [i["id"] for i in items] == ["new", "old"]


def test_history_trim_keeps_running(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "MAX_HISTORY", 5)
    for i in range(7):
        job_store.create(f"done-{i}", kind="x", ts="1",
                         started_at=float(i))
        job_store.update(f"done-{i}", status="completed")
    job_store.create("running-1", kind="x", ts="1", started_at=100.0)

    items = job_store.list_all()
    ids = [i["id"] for i in items]
    assert "running-1" in ids
    assert len(items) <= 5 + 1


def test_get_returns_none_when_absent():
    assert job_store.get("missing") is None


def test_corrupted_jobs_json_returns_empty(tmp_path, monkeypatch):
    p = tmp_path / "jobs.json"
    p.write_text("not json", encoding="utf-8")
    assert job_store.list_all() == []


def test_disk_format_is_valid_json(tmp_path):
    job_store.create("a", kind="x", ts="1")
    p = os.path.join(os.environ["JOB_STORE_DIR"], "jobs.json")
    with open(p) as f:
        data = json.load(f)
    assert "jobs" in data
    assert "a" in data["jobs"]
