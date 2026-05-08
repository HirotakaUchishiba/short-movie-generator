"""staged_pipeline.run_next_stage が stage 完了 / 失敗時に
generation_records.stage_runs を更新することを確認する。

Phase 0 の計測基盤として、`run_next_stage` のフックは pipeline 自体の
動作には影響を与えてはならない (= analytics DB エラーは warn だけで握りつぶす)。
"""
import json
import os

import pytest

import progress_store
import staged_pipeline


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()

    ts = "20260507_220000"
    ts_dir = tmp_path / "temp" / ts
    ts_dir.mkdir(parents=True)
    return str(ts_dir), ts, _db


def _stub_runner_success(*args, **kwargs):
    pass


def _stub_runner_fail(*args, **kwargs):
    raise RuntimeError("boom")


def test_run_next_stage_records_completed(project_dir, monkeypatch):
    ts_dir, ts, db = project_dir
    monkeypatch.setitem(staged_pipeline.STAGE_RUNNERS, "script",
                        _stub_runner_success)

    # script は最初の stage = next_stage(ts_dir) は "script"
    # stub 成功 → mark_generated は呼ばれないが record だけ確認
    res = staged_pipeline.run_next_stage({}, "test_name", ts_dir)
    assert res == "script"

    rec = db.get_generation_record(ts)
    assert rec is not None
    runs = json.loads(rec["stage_runs"])
    assert len(runs) == 1
    assert runs[0]["stage"] == "script"
    assert runs[0]["status"] == "completed"
    assert runs[0]["started_at"]
    assert runs[0]["ended_at"]


def test_run_next_stage_records_failed_and_reraises(project_dir, monkeypatch):
    ts_dir, ts, db = project_dir
    monkeypatch.setitem(staged_pipeline.STAGE_RUNNERS, "script",
                        _stub_runner_fail)

    with pytest.raises(RuntimeError, match="boom"):
        staged_pipeline.run_next_stage({}, "test_name", ts_dir)

    rec = db.get_generation_record(ts)
    runs = json.loads(rec["stage_runs"])
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert "boom" in runs[0]["error"]


def test_run_next_stage_records_per_stage_separately(project_dir, monkeypatch):
    """script → tts と進めると stage_runs が 2 件残る。"""
    ts_dir, ts, db = project_dir

    def _ok_and_mark(stage):
        def _runner(*args, **kwargs):
            progress_store.mark_generated(ts_dir, stage)
            progress_store.mark_approved(ts_dir, stage)
        return _runner

    monkeypatch.setitem(staged_pipeline.STAGE_RUNNERS, "script",
                        _ok_and_mark("script"))
    monkeypatch.setitem(staged_pipeline.STAGE_RUNNERS, "tts",
                        _ok_and_mark("tts"))

    staged_pipeline.run_next_stage({}, "n", ts_dir)
    staged_pipeline.run_next_stage({}, "n", ts_dir)

    runs = json.loads(db.get_generation_record(ts)["stage_runs"])
    assert [r["stage"] for r in runs] == ["script", "tts"]
    assert all(r["status"] == "completed" for r in runs)


def test_run_next_stage_does_not_fail_when_db_unwritable(
    project_dir, monkeypatch,
):
    """analytics DB エラーは warn だけ、pipeline は止まらない。"""
    ts_dir, ts, db = project_dir
    monkeypatch.setitem(staged_pipeline.STAGE_RUNNERS, "script",
                        _stub_runner_success)
    monkeypatch.setattr(
        "analytics.db.append_stage_run",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    res = staged_pipeline.run_next_stage({}, "n", ts_dir)
    assert res == "script"
