"""errors.classify の 8 種 + unknown 分類と build_error_detail の test。"""
from __future__ import annotations

import pytest

from errors.classify import (
    ERROR_TYPES,
    build_error_detail,
    classify_error,
)


# ─────────── classify_error ───────────


@pytest.mark.parametrize(
    "text,expected",
    [
        # credit_exhausted (= Anthropic / OpenAI / fal.ai)
        (
            "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error',"
            " 'message': 'Your credit balance is too low to access the Anthropic API.'}}",
            "credit_exhausted",
        ),
        ("Out of credits", "credit_exhausted"),
        ("exhausted balance", "credit_exhausted"),
        ("insufficient credit on account", "credit_exhausted"),
        # context_too_long
        ("Input is too long for the model: 250000 tokens", "context_too_long"),
        ("context window exceeded", "context_too_long"),
        # auth_failure
        ("invalid api key", "auth_failure"),
        ("Error 401: Unauthorized", "auth_failure"),
        ("authentication_error: missing key", "auth_failure"),
        # rate_limit
        ("Error 429: Too Many Requests", "rate_limit"),
        ("rate limit reached", "rate_limit"),
        # quota_exceeded
        ("Daily quota exceeded for project foo", "quota_exceeded"),
        ("monthly limit hit", "quota_exceeded"),
        # safety_filter
        ("Content blocked by safety filter", "safety_filter"),
        ("responsibleAI policy violation", "safety_filter"),
        # network_timeout
        ("APIConnectionError: connection refused", "network_timeout"),
        ("socket.timeout: read timed out", "network_timeout"),
        # disk_full
        ("OSError: [Errno 28] No space left on device", "disk_full"),
        ("ENOSPC", "disk_full"),
        # unknown
        ("Some completely novel error xyz", "unknown"),
        ("", "unknown"),
    ],
)
def test_classify_error_known_patterns(text: str, expected: str) -> None:
    assert classify_error(text) == expected


def test_classify_error_accepts_exception() -> None:
    e = RuntimeError("Your credit balance is too low")
    assert classify_error(e) == "credit_exhausted"


def test_classify_error_handles_none() -> None:
    assert classify_error(None) == "unknown"


def test_error_types_constant_covers_all() -> None:
    # build_error_detail が返しうる type が全て ERROR_TYPES に含まれていること
    expected = {
        "credit_exhausted", "rate_limit", "auth_failure", "quota_exceeded",
        "context_too_long", "safety_filter", "network_timeout", "disk_full",
        "unknown",
    }
    assert set(ERROR_TYPES) == expected


# ─────────── build_error_detail ───────────


def test_build_error_detail_full_envelope() -> None:
    text = (
        "Error code: 400 - {'type': 'error', 'request_id': 'req_011CavqQUqWoWA18',"
        " 'message': 'Your credit balance is too low'}"
    )
    detail = build_error_detail(text, retry_cost_estimate_usd=3.30)
    assert detail["type"] == "credit_exhausted"
    assert "credit balance" in detail["message"]
    assert detail["request_id"] == "req_011CavqQUqWoWA18"
    assert "クレジット" in detail["actionable_hint"]
    assert detail["retry_cost_estimate_usd"] == 3.30
    assert "T" in detail["occurred_at"]  # ISO8601


def test_build_error_detail_truncates_long_message() -> None:
    huge = "x" * 5000
    detail = build_error_detail(huge)
    assert len(detail["message"]) == 2000


def test_build_error_detail_actionable_hint_override() -> None:
    detail = build_error_detail(
        "credit balance is too low",
        actionable_hint="カスタム hint",
    )
    assert detail["actionable_hint"] == "カスタム hint"


def test_build_error_detail_no_request_id_when_absent() -> None:
    detail = build_error_detail("Generic failure with no id")
    assert detail["request_id"] is None


def test_build_error_detail_handles_none_input() -> None:
    detail = build_error_detail(None)
    assert detail["type"] == "unknown"
    assert detail["message"] == ""
    assert detail["request_id"] is None
