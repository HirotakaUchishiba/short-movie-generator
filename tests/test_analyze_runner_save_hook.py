"""analyze.runner._PhaseTracker._on_save_complete + _mark_project_analyze_failed
の単体テスト (= from-reference-video 経路の Stage 0 → Stage 1 unlock hook)。
"""
import json
import os

import pytest


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """analytics DB と TEMP_DIR を tmp_path に隔離する。"""
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    import config
    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path / "temp"))
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    return tmp_path


def _write_screenplay_output(tmp_path, name="auto_xxx.json") -> str:
    """analyze pipeline の save 出力を simulate (= screenplays/auto_<sha>.json)。"""
    out = tmp_path / name
    out.write_text(
        json.dumps({"caption": "demo", "scenes": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(out)


def _make_project(temp_dir: str, ts: str = "20260510_120000") -> str:
    """temp/<TS>/ ディレクトリを作って analyze_job_id を init した状態にする。"""
    import progress_store
    import staged_pipeline
    project_path = os.path.join(temp_dir, ts)
    os.makedirs(project_path, exist_ok=True)
    staged_pipeline.init_pending_metadata(project_path, "analyze_job_xxx")
    progress_store.mark_analyze_started(project_path)
    return project_path


def test_save_hook_no_op_when_project_ts_none(isolated_env) -> None:
    """standalone analyze (= project_ts=None) では何もしない。"""
    from analyze import job as analyze_job
    from analyze.runner import _PhaseTracker

    j = analyze_job.create_job("sha", {})  # project_ts default None
    tracker = _PhaseTracker(j.id)
    # 何の例外も起きず return することを確認
    tracker._on_save_complete({"output_path": "/nonexistent"})


def test_save_hook_handles_missing_output_path(isolated_env, caplog) -> None:
    """output_path が data に無い場合は error log だけで終了。"""
    import config

    from analyze import job as analyze_job
    from analyze.runner import _PhaseTracker

    project_path = _make_project(config.TEMP_DIR)
    j = analyze_job.create_job("sha", {}, project_ts="20260510_120000")
    tracker = _PhaseTracker(j.id)
    tracker._on_save_complete({})  # output_path 無し
    # progress は変化なし (= まだ running 状態のまま)
    import progress_store
    assert progress_store.analyze_status(project_path) == "running"


def test_save_hook_handles_missing_project_dir(isolated_env) -> None:
    """project_ts セット済みだが TEMP_DIR/<TS>/ が存在しない (= 削除済み)。"""
    from analyze import job as analyze_job
    from analyze.runner import _PhaseTracker

    j = analyze_job.create_job("sha", {}, project_ts="20260510_999999")
    tracker = _PhaseTracker(j.id)
    # raise しないこと
    tracker._on_save_complete({"output_path": str(isolated_env / "x.json")})


def test_save_hook_unlocks_stage_1(isolated_env) -> None:
    """正常系: snapshot コピー + metadata + Stage 0/1 unlock。"""
    import config

    import progress_store
    import staged_pipeline
    from analyze import job as analyze_job
    from analyze.runner import _PhaseTracker

    ts = "20260510_120000"
    project_path = _make_project(config.TEMP_DIR, ts)
    output_path = _write_screenplay_output(isolated_env, "auto_abc.json")

    j = analyze_job.create_job("sha", {}, project_ts=ts)
    tracker = _PhaseTracker(j.id)
    tracker._on_save_complete({"output_path": output_path})

    # snapshot がコピーされている
    snap = staged_pipeline.project_screenplay_path(project_path)
    assert os.path.exists(snap)
    with open(snap) as f:
        assert json.load(f)["caption"] == "demo"

    # metadata が update されている
    meta = staged_pipeline.read_metadata(project_path)
    assert meta["screenplay_name"] == "auto_abc.json"
    assert meta["screenplay_path"] == "screenplay.json"
    assert meta["screenplay_sha256"]
    # init で書いた値は維持
    assert meta["analyze_job_id"] == "analyze_job_xxx"

    # Stage 0 完了 + Stage 1 unlock
    assert progress_store.analyze_status(project_path) == "completed"
    p = progress_store.load(project_path)
    assert p["stages"]["script"]["generated_at"]
    assert p["stages"]["script"]["approved_at"]


def test_save_hook_writes_hook_error_on_failure(
    isolated_env, monkeypatch,
) -> None:
    """shutil.copyfile が失敗しても analyze は成功扱い、metadata に hook_error。"""
    import shutil

    import config
    import staged_pipeline
    from analyze import job as analyze_job
    from analyze.runner import _PhaseTracker

    ts = "20260510_120000"
    project_path = _make_project(config.TEMP_DIR, ts)
    output_path = _write_screenplay_output(isolated_env, "auto_abc.json")

    j = analyze_job.create_job("sha", {}, project_ts=ts)
    tracker = _PhaseTracker(j.id)

    def boom(*_a, **_kw):
        raise OSError("simulated copy failure")

    monkeypatch.setattr(shutil, "copyfile", boom)
    tracker._on_save_complete({"output_path": output_path})

    meta = staged_pipeline.read_metadata(project_path)
    assert "save hook failed" in (meta.get("analyze_hook_error") or "")


def test_mark_project_analyze_failed_no_op_when_dir_missing(
    isolated_env,
) -> None:
    """temp/<TS>/ 不在なら raise せず no-op。"""
    from analyze.runner import _mark_project_analyze_failed
    _mark_project_analyze_failed("99999999_999999", "anything")  # raise しない


def test_mark_project_analyze_failed_writes_status(isolated_env) -> None:
    """temp/<TS>/ あり → progress.stages.analyze.status='failed'。"""
    import config

    import progress_store
    from analyze.runner import _mark_project_analyze_failed

    ts = "20260510_120000"
    project_path = _make_project(config.TEMP_DIR, ts)
    _mark_project_analyze_failed(ts, "cost gate timeout")
    assert progress_store.analyze_status(project_path) == "failed"
    p = progress_store.load(project_path)
    assert p["stages"]["analyze"]["error"] == "cost gate timeout"
