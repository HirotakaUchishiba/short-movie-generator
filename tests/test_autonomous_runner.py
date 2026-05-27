"""scripts.autonomous_runner.run_loop の単体テスト。

auto_loop.run_one_video は DI で差し替え、budget / kill / task_queue は monkeypatch
してループ制御を検証する。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from autonomous import task_queue


def _load_runner():
    path = Path(__file__).resolve().parent.parent / "scripts" / "autonomous_runner.py"
    spec = importlib.util.spec_from_file_location("autonomous_runner", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bind_queue_to(monkeypatch, p):
    """task_queue.next_pending / mark をテスト用 path に束ねる (元関数を保持して再帰回避)。"""
    orig_next = task_queue.next_pending
    orig_mark = task_queue.mark
    monkeypatch.setattr(task_queue, "next_pending", lambda: orig_next(path=p))
    monkeypatch.setattr(
        task_queue, "mark",
        lambda jid, status, **kw: orig_mark(jid, status, path=p, **kw))


def test_processes_pending_then_stops_when_empty(tmp_path, monkeypatch):
    runner = _load_runner()
    p = str(tmp_path / "q.jsonl")
    task_queue.enqueue("https://a", "cc", path=p)
    task_queue.enqueue("https://b", "cc", path=p)
    monkeypatch.setattr(runner, "_kill_requested", lambda: False)
    monkeypatch.setattr(runner, "_budget_blocked", lambda: False)
    _bind_queue_to(monkeypatch, p)

    calls = []

    def fake_run(url, *, license_status, dry_run=False):
        calls.append(url)
        return "20260527_000000"

    processed = runner.run_loop(poll=0, run_video=fake_run, dry_run=True, drain=True)
    assert processed == 2
    assert calls == ["https://a", "https://b"]
    assert len(task_queue.list_jobs(status="done", path=p)) == 2


def test_failed_job_continues_to_next(tmp_path, monkeypatch):
    runner = _load_runner()
    p = str(tmp_path / "q.jsonl")
    task_queue.enqueue("https://bad", "cc", path=p)
    task_queue.enqueue("https://good", "cc", path=p)
    monkeypatch.setattr(runner, "_kill_requested", lambda: False)
    monkeypatch.setattr(runner, "_budget_blocked", lambda: False)
    _bind_queue_to(monkeypatch, p)

    from scripts.auto_loop import AutoLoopAborted

    def fake_run(url, *, license_status, dry_run=False):
        if "bad" in url:
            raise AutoLoopAborted("simulated failure")
        return "ts_ok"

    processed = runner.run_loop(poll=0, run_video=fake_run, drain=True)
    assert processed == 1  # good のみ成功
    assert len(task_queue.list_jobs(status="failed", path=p)) == 1
    assert len(task_queue.list_jobs(status="done", path=p)) == 1


def test_kill_switch_stops_loop(tmp_path, monkeypatch):
    runner = _load_runner()
    p = str(tmp_path / "q.jsonl")
    task_queue.enqueue("https://a", "cc", path=p)
    monkeypatch.setattr(runner, "_kill_requested", lambda: True)  # 即停止
    monkeypatch.setattr(runner, "_budget_blocked", lambda: False)
    _bind_queue_to(monkeypatch, p)
    called = []
    processed = runner.run_loop(poll=0, run_video=lambda *a, **k: called.append(1))
    assert processed == 0 and called == []  # kill で何も処理しない


def test_budget_block_stops_loop(tmp_path, monkeypatch):
    runner = _load_runner()
    p = str(tmp_path / "q.jsonl")
    task_queue.enqueue("https://a", "cc", path=p)
    monkeypatch.setattr(runner, "_kill_requested", lambda: False)
    monkeypatch.setattr(runner, "_budget_blocked", lambda: True)  # 予算超過
    _bind_queue_to(monkeypatch, p)
    called = []
    processed = runner.run_loop(poll=0, run_video=lambda *a, **k: called.append(1))
    assert processed == 0 and called == []
