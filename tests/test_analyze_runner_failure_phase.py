"""_PhaseTracker.fail_current_phase + _mark_project_analyze_failed の
phase 情報伝播テスト。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import progress_store


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path / "temp"))
    return tmp_path


# ─────────── _PhaseTracker.fail_current_phase ───────────


def test_phase_tracker_fail_current_phase_returns_phase_name(isolated_env) -> None:
    from analyze.runner import _PhaseTracker

    tracker = _PhaseTracker("job_test_001")
    with patch("analyze.job.start_phase"), patch("analyze.job.fail_phase") as mfail:
        tracker.handle("phase_start", {"phase": "claude"})
        assert tracker.current_phase == "claude"

        phase = tracker.fail_current_phase(RuntimeError("credit balance low"))

    assert phase == "claude"
    assert tracker.current_phase is None
    mfail.assert_called_once()
    call_args = mfail.call_args
    assert call_args[0][0] == "job_test_001"
    assert call_args[0][1] == "claude"
    assert "credit balance low" in call_args[0][2]


def test_phase_tracker_fail_current_phase_noop_when_no_active_phase(isolated_env) -> None:
    from analyze.runner import _PhaseTracker

    tracker = _PhaseTracker("job_test_002")
    with patch("analyze.job.fail_phase") as mfail:
        phase = tracker.fail_current_phase("anything")
    assert phase is None
    mfail.assert_not_called()


def test_phase_tracker_phase_complete_clears_current(isolated_env) -> None:
    from analyze.runner import _PhaseTracker

    tracker = _PhaseTracker("job_test_003")
    with patch("analyze.job.start_phase"), patch("analyze.job.complete_phase"):
        tracker.handle("phase_start", {"phase": "frames"})
        assert tracker.current_phase == "frames"
        tracker.handle("phase_complete", {"phase": "frames"})
        assert tracker.current_phase is None


# ─────────── _mark_project_analyze_failed (= structured envelope 経路) ───────────


def test_mark_project_analyze_failed_writes_structured_detail(isolated_env) -> None:
    import os
    from analyze.runner import _mark_project_analyze_failed

    ts = "20260511_220521"
    ts_path = os.path.join(str(isolated_env / "temp"), ts)
    os.makedirs(ts_path)

    _mark_project_analyze_failed(
        ts,
        "Error code: 400 'Your credit balance is too low' "
        "request_id: req_011CavqQUq",
        failed_phase="claude",
    )

    p = progress_store.load(ts_path)
    block = p["stages"]["analyze"]
    assert block["status"] == "failed"
    assert block["generated_at"] is not None  # analyze の既存挙動を維持
    detail = block["error_detail"]
    assert detail["type"] == "credit_exhausted"
    assert detail["failed_phase"] == "claude"
    assert detail["request_id"] == "req_011CavqQUq"
    assert "クレジット" in detail["actionable_hint"]


def test_mark_project_analyze_failed_no_op_when_dir_missing(isolated_env) -> None:
    """temp/<TS> が無い場合は静かに no-op (= 既存挙動)。"""
    from analyze.runner import _mark_project_analyze_failed
    _mark_project_analyze_failed("99999999_999999", "anything")  # raise しない


def test_mark_project_analyze_failed_classifier_handles_runner_error_prefix(
    isolated_env,
) -> None:
    """`_run_job` が `runner error: <e>` の prefix を付けて呼ぶ経路でも classify は機能する。"""
    import os
    from analyze.runner import _mark_project_analyze_failed

    ts = "20260511_220522"
    ts_path = os.path.join(str(isolated_env / "temp"), ts)
    os.makedirs(ts_path)

    _mark_project_analyze_failed(
        ts,
        "runner error: Error code: 401 invalid api key",
        failed_phase="claude",
    )

    p = progress_store.load(ts_path)
    detail = p["stages"]["analyze"]["error_detail"]
    assert detail["type"] == "auth_failure"
