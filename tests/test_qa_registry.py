"""Phase 2: stage → validator マッピング + 一括実行 helper のテスト。"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_run_validators_returns_empty_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("config.QA_VALIDATORS_ENABLED", False)
    from qa.registry import run_validators_for_stage
    assert run_validators_for_stage(str(tmp_path), "tts") == []


def test_blacklist_skips_individual_validator(tmp_path, monkeypatch):
    monkeypatch.setattr("config.QA_VALIDATORS_ENABLED", True)
    monkeypatch.setattr("config.QA_VALIDATOR_BLACKLIST",
                        ("audio_silence", "audio_clipping"))
    from qa.registry import run_validators_for_stage
    # tts stage で audio_silence と audio_clipping を blacklist → story_pacing 残る
    sp = {"scenes": [{"lines": [{"text": "x", "start": 0.0, "end": 5.0}]}]}
    results = run_validators_for_stage(str(tmp_path), "tts", screenplay=sp)
    # story_pacing だけが走る前提
    assert all(r.tag != "audio_silence" for r in results if r.tag)
    assert all(r.tag != "audio_clipping" for r in results if r.tag)


def test_validator_crash_does_not_abort_others(tmp_path, monkeypatch):
    monkeypatch.setattr("config.QA_VALIDATORS_ENABLED", True)
    monkeypatch.setattr("config.QA_VALIDATOR_BLACKLIST", ())
    # audio_silence を crash させる → audio_clipping / story_pacing は走り続ける
    with patch("qa.registry.check_audio_silence",
               side_effect=RuntimeError("boom")):
        from qa.registry import run_validators_for_stage
        sp = {"scenes": [{"lines": [{"text": "x", "start": 0.0, "end": 5.0}]}]}
        results = run_validators_for_stage(str(tmp_path), "tts", screenplay=sp)
    # crash した validator の結果は無いが、他の validator は呼ばれて結果を持つ
    # (ts_path が空なので audio_clipping は何も返さないが、story_pacing は返す)
    assert any(r.tag != "audio_silence" or r.passed for r in results)


def test_aggregate_scores_handles_empty():
    from qa.registry import aggregate_scores
    assert aggregate_scores([]) == {
        "count": 0, "passed": 0, "failed": 0, "avg_score": 0.0,
    }


def test_aggregate_scores_mixed():
    from qa.registry import aggregate_scores
    from qa.validators.base import passed_result, failed_result
    scores = aggregate_scores([
        passed_result(score=0.9),
        passed_result(score=0.8),
        failed_result(score=0.2, reason="x", tag="audio_silence"),
    ])
    assert scores["count"] == 3
    assert scores["passed"] == 2
    assert scores["failed"] == 1
    assert scores["avg_score"] == pytest.approx((0.9 + 0.8 + 0.2) / 3)


def test_stage_validator_names_lists_known_stages():
    from qa.registry import stage_validator_names
    assert "audio_silence" in stage_validator_names("tts")
    assert "subtitle_overlap" in stage_validator_names("bg")
    assert "character_drift" in stage_validator_names("kling")
    assert stage_validator_names("nonexistent") == []
