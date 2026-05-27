"""autonomous.dev_backlog の単体テスト。"""
from __future__ import annotations

from autonomous import dev_backlog


def _p(tmp_path):
    return str(tmp_path / "dev_backlog.jsonl")


def test_next_pending_orders_by_priority_then_created(tmp_path):
    p = _p(tmp_path)
    dev_backlog.add("low", priority=5, path=p)
    high = dev_backlog.add("high", priority=1, path=p)
    dev_backlog.add("mid", priority=3, path=p)
    assert dev_backlog.next_pending(path=p)["id"] == high  # priority 1 が先頭


def test_mark_done_advances_and_records_pr(tmp_path):
    p = _p(tmp_path)
    t1 = dev_backlog.add("t1", priority=1, path=p)
    dev_backlog.add("t2", priority=2, path=p)
    dev_backlog.mark(t1, "done", branch="feat/x", pr="#999", path=p)
    nxt = dev_backlog.next_pending(path=p)
    assert nxt["title"] == "t2"
    done = dev_backlog.list_tasks(status="done", path=p)
    assert len(done) == 1 and done[0]["pr"] == "#999" and done[0]["branch"] == "feat/x"


def test_mark_failed_records_error(tmp_path):
    p = _p(tmp_path)
    tid = dev_backlog.add("boom", path=p)
    dev_backlog.mark(tid, "failed", error="tests red", path=p)
    failed = dev_backlog.list_tasks(status="failed", path=p)
    assert len(failed) == 1 and failed[0]["error"] == "tests red"
    assert dev_backlog.next_pending(path=p) is None


def test_in_progress_not_returned_by_next_pending(tmp_path):
    p = _p(tmp_path)
    tid = dev_backlog.add("wip", path=p)
    dev_backlog.mark(tid, "in_progress", path=p)
    assert dev_backlog.next_pending(path=p) is None


def test_mark_invalid_status_raises(tmp_path):
    p = _p(tmp_path)
    tid = dev_backlog.add("x", path=p)
    import pytest
    with pytest.raises(ValueError):
        dev_backlog.mark(tid, "bogus", path=p)


def test_empty_backlog(tmp_path):
    assert dev_backlog.next_pending(path=_p(tmp_path)) is None
    assert dev_backlog.list_tasks(path=_p(tmp_path)) == []
