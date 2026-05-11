"""progress_store.mark_stage_failed + mark_analyze_failed の構造化 envelope を検証。"""
from __future__ import annotations

import pytest

import progress_store
from errors import build_error_detail


@pytest.fixture
def ts_path(tmp_path):
    """新規 project の temp ディレクトリを 1 つ用意する。"""
    return str(tmp_path)


# ─────────── mark_stage_failed (= generic 経路) ───────────


def test_mark_stage_failed_writes_structured_envelope(ts_path: str) -> None:
    detail = build_error_detail("Out of credits", retry_cost_estimate_usd=1.20)
    progress_store.mark_stage_failed(ts_path, "tts", detail)

    p = progress_store.load(ts_path)
    block = p["stages"]["tts"]
    assert block["status"] == "failed"
    assert block["error_detail"]["type"] == "credit_exhausted"
    assert block["error_detail"]["retry_cost_estimate_usd"] == 1.20
    assert block["error"] == "Out of credits"  # legacy field
    # 非 analyze stage は generated_at を立てない
    assert block["generated_at"] is None
    assert block["approved_at"] is None
    assert block["regen_count"] == 0


def test_mark_stage_failed_preserves_regen_count(ts_path: str) -> None:
    """既に走った regen_count を破壊しない。"""
    progress_store.increment_regen(ts_path, "tts")
    progress_store.increment_regen(ts_path, "tts")
    assert progress_store.load(ts_path)["stages"]["tts"]["regen_count"] == 2

    detail = build_error_detail("rate limit reached")
    progress_store.mark_stage_failed(ts_path, "tts", detail)

    assert progress_store.load(ts_path)["stages"]["tts"]["regen_count"] == 2


def test_mark_stage_failed_does_not_affect_other_stages(ts_path: str) -> None:
    """1 stage の failure が他 stage の status を壊さないこと。"""
    progress_store.mark_generated(ts_path, "script")
    progress_store.mark_approved(ts_path, "script")
    progress_store.mark_generated(ts_path, "tts")

    detail = build_error_detail("disk full")
    progress_store.mark_stage_failed(ts_path, "bg", detail)

    p = progress_store.load(ts_path)
    assert p["stages"]["script"]["approved_at"] is not None
    assert p["stages"]["tts"]["generated_at"] is not None
    assert p["stages"]["bg"]["status"] == "failed"


def test_mark_stage_failed_rejects_unknown_stage(ts_path: str) -> None:
    with pytest.raises(ValueError, match="unknown stage"):
        progress_store.mark_stage_failed(ts_path, "bogus", {"type": "unknown"})


def test_mark_stage_failed_truncates_legacy_error_field(ts_path: str) -> None:
    huge_msg = "x" * 5000
    detail = build_error_detail(huge_msg)
    progress_store.mark_stage_failed(ts_path, "kling", detail)
    p = progress_store.load(ts_path)
    # legacy error field は :500
    assert len(p["stages"]["kling"]["error"]) == 500
    # error_detail.message は :2000
    assert len(p["stages"]["kling"]["error_detail"]["message"]) == 2000


# ─────────── mark_analyze_failed (= 後方互換 wrapper) ───────────


def test_mark_analyze_failed_preserves_legacy_behavior(ts_path: str) -> None:
    """analyze は generated_at を now にセットし、status=failed にする。"""
    progress_store.mark_analyze_failed(ts_path, "Your credit balance is too low")
    p = progress_store.load(ts_path)
    block = p["stages"]["analyze"]
    assert block["status"] == "failed"
    assert block["generated_at"] is not None  # ← analyze の既存挙動
    assert block["approved_at"] is None
    assert "credit balance" in block["error"]  # legacy field


def test_mark_analyze_failed_writes_structured_envelope(ts_path: str) -> None:
    progress_store.mark_analyze_failed(
        ts_path,
        "Error code: 400 'credit balance is too low' request_id: req_011Cavq",
    )
    p = progress_store.load(ts_path)
    detail = p["stages"]["analyze"]["error_detail"]
    assert detail["type"] == "credit_exhausted"
    assert detail["request_id"] == "req_011Cavq"
    assert "クレジット" in detail["actionable_hint"]
