import json
import os
from pathlib import Path

import pytest

import cost_estimator


@pytest.fixture(autouse=True)
def _isolate_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cost_estimator.config, "COST_HISTORY_PATH",
                        str(tmp_path / "cost_history.jsonl"))
    monkeypatch.setattr(cost_estimator.config, "REPORTS_DIR", str(tmp_path))


def _screenplay(n_scenes: int, duration: float = 5.0, with_lines: bool = True) -> dict:
    scene = lambda: {
        "duration": duration,
        "background_prompt": "オフィス",
        "lines": ([{"text": "転職", "start": 0.0}] if with_lines else []),
    }
    return {
        "caption": "テストキャプション",
        "scenes": [scene() for _ in range(n_scenes)],
    }


def test_estimate_default_rates() -> None:
    est = cost_estimator.estimate(_screenplay(10))
    assert est["backgrounds"] == 10
    assert est["scenes"] == 10
    assert est["video_seconds"] > 0
    assert est["cost_usd"] > 0
    assert "rates" in est


def test_record_writes_jsonl() -> None:
    sp = _screenplay(3)
    est = cost_estimator.estimate(sp)
    actual = {
        "video_time": 60.0, "compose_time": 5.0, "total_time": 65.0,
        "video_seconds": 20, "total_cost": 2.0,
    }
    cost_estimator.record("20260501_120000", sp, actual, est)

    assert os.path.exists(cost_estimator.config.COST_HISTORY_PATH)
    with open(cost_estimator.config.COST_HISTORY_PATH) as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["ts"] == "20260501_120000"
    assert entry["actual"]["total_cost"] == 2.0
    assert entry["scenes"] == 3


def test_rates_calibrate_from_history() -> None:
    sp = _screenplay(2)
    est = cost_estimator.estimate(sp)
    actual = {
        "video_time": 100.0, "compose_time": 6.0, "total_time": 106.0,
        "video_seconds": 10, "total_cost": 1.1,
    }
    for i in range(3):
        cost_estimator.record(f"2026050{i}_000000", sp, actual, est)

    new_est = cost_estimator.estimate(sp)
    assert new_est["rates"]["compose_seconds_per_segment"] == pytest.approx(3.0, rel=0.2)


def test_format_estimate_contains_numbers() -> None:
    est = cost_estimator.estimate(_screenplay(2))
    msg = cost_estimator.format_estimate(est)
    assert "予想" in msg
    assert "$" in msg


def test_format_comparison_shows_diff() -> None:
    est = {"time_seconds": 60.0, "cost_usd": 1.0}
    actual = {"total_time": 66.0, "total_cost": 1.1}
    table = cost_estimator.format_comparison(est, actual)
    assert "+10.0%" in table


def test_estimate_includes_lipsync_cost_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(cost_estimator.config, "LIPSYNC_ENABLED", True)
    monkeypatch.setattr(cost_estimator.config, "LIPSYNC_COST_PER_SECOND", 0.05)
    est = cost_estimator.estimate(_screenplay(3))
    assert est["lipsync_seconds"] > 0
    expected_lipsync_cost = est["lipsync_seconds"] * 0.05
    expected_base_cost = (est["backgrounds"] * cost_estimator.COST_PER_IMAGE
                          + est["video_seconds"] * cost_estimator.COST_VIDEO_PER_SECOND)
    assert est["cost_usd"] == pytest.approx(expected_base_cost + expected_lipsync_cost)


def test_estimate_excludes_lipsync_cost_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(cost_estimator.config, "LIPSYNC_ENABLED", False)
    est = cost_estimator.estimate(_screenplay(3))
    assert est["lipsync_seconds"] == 0


def test_estimate_excludes_lipsync_in_silent_mode(monkeypatch) -> None:
    monkeypatch.setattr(cost_estimator.config, "LIPSYNC_ENABLED", True)
    sp = _screenplay(3)
    sp["audio_mode"] = "silent"
    est = cost_estimator.estimate(sp)
    assert est["lipsync_seconds"] == 0


def test_estimate_respects_per_scene_opt_out(monkeypatch) -> None:
    monkeypatch.setattr(cost_estimator.config, "LIPSYNC_ENABLED", True)
    sp = {
        "caption": "t",
        "scenes": [
            {"duration": 5.0, "background_prompt": "p",
             "lines": [{"text": "a", "start": 0.0}]},
            {"duration": 5.0, "background_prompt": "p", "lipsync": False,
             "lines": [{"text": "b", "start": 0.0}]},
            {"duration": 5.0, "background_prompt": "p",
             "lines": [{"text": "c", "start": 0.0}]},
        ],
    }
    est = cost_estimator.estimate(sp)
    sp_all = _screenplay(3)
    est_all = cost_estimator.estimate(sp_all)
    assert est["lipsync_seconds"] < est_all["lipsync_seconds"]


def test_estimate_scene_without_lines_skips_lipsync(monkeypatch) -> None:
    monkeypatch.setattr(cost_estimator.config, "LIPSYNC_ENABLED", True)
    sp = _screenplay(3, with_lines=False)
    est = cost_estimator.estimate(sp)
    assert est["lipsync_seconds"] == 0


def test_format_estimate_includes_lipsync_label(monkeypatch) -> None:
    monkeypatch.setattr(cost_estimator.config, "LIPSYNC_ENABLED", True)
    est = cost_estimator.estimate(_screenplay(2))
    msg = cost_estimator.format_estimate(est)
    assert "リップシンク" in msg
