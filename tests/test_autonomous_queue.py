"""autonomous.task_queue の単体テスト。"""
from __future__ import annotations

from autonomous import task_queue


def _qpath(tmp_path):
    return str(tmp_path / "url_queue.jsonl")


def test_enqueue_then_next_pending_fifo(tmp_path):
    p = _qpath(tmp_path)
    id1 = task_queue.enqueue("https://a", "cc", path=p)
    id2 = task_queue.enqueue("https://b", "cc", path=p)
    job = task_queue.next_pending(path=p)
    assert job["id"] == id1  # FIFO
    assert job["url"] == "https://a"
    assert id1 != id2


def test_mark_done_advances_queue(tmp_path):
    p = _qpath(tmp_path)
    id1 = task_queue.enqueue("https://a", "cc", path=p)
    task_queue.enqueue("https://b", "cc", path=p)
    assert task_queue.mark(id1, "done", ts="20260527_000000", path=p)
    nxt = task_queue.next_pending(path=p)
    assert nxt["url"] == "https://b"  # 次の pending に進む
    done = task_queue.list_jobs(status="done", path=p)
    assert len(done) == 1 and done[0]["ts"] == "20260527_000000"


def test_mark_failed_records_error(tmp_path):
    p = _qpath(tmp_path)
    jid = task_queue.enqueue("https://x", "cc", path=p)
    task_queue.mark(jid, "failed", error="boom", path=p)
    failed = task_queue.list_jobs(status="failed", path=p)
    assert len(failed) == 1 and failed[0]["error"] == "boom"
    assert task_queue.next_pending(path=p) is None  # pending 無し


def test_mark_invalid_status_raises(tmp_path):
    p = _qpath(tmp_path)
    jid = task_queue.enqueue("https://x", "cc", path=p)
    import pytest
    with pytest.raises(ValueError):
        task_queue.mark(jid, "bogus", path=p)


def test_next_pending_empty_returns_none(tmp_path):
    assert task_queue.next_pending(path=_qpath(tmp_path)) is None


def test_corrupt_line_is_skipped(tmp_path):
    p = _qpath(tmp_path)
    task_queue.enqueue("https://ok", "cc", path=p)
    with open(p, "a", encoding="utf-8") as f:
        f.write("{ this is not json\n")
    jobs = task_queue.list_jobs(path=p)
    assert len(jobs) == 1  # 壊れた行は無視
