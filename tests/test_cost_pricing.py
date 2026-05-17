"""cost_tracking.pricing の単体テスト (units → USD 純粋関数)。"""
from __future__ import annotations

import pytest

from cost_tracking import pricing


def test_anthropic_cost_input_only() -> None:
    cost = pricing.compute_anthropic_cost(
        input_tokens=1_000_000,
        output_tokens=0,
        unit_prices={"input_per_mtok": 15.0, "output_per_mtok": 75.0},
    )
    assert cost == pytest.approx(15.0)


def test_anthropic_cost_output_only() -> None:
    cost = pricing.compute_anthropic_cost(
        input_tokens=0,
        output_tokens=1_000_000,
        unit_prices={"input_per_mtok": 15.0, "output_per_mtok": 75.0},
    )
    assert cost == pytest.approx(75.0)


def test_anthropic_cost_combined() -> None:
    cost = pricing.compute_anthropic_cost(
        input_tokens=200_000,
        output_tokens=12_000,
        unit_prices={"input_per_mtok": 15.0, "output_per_mtok": 75.0},
    )
    expected = (200_000 * 15.0 + 12_000 * 75.0) / 1_000_000
    assert cost == pytest.approx(expected)


def test_elevenlabs_cost() -> None:
    cost = pricing.compute_elevenlabs_cost(
        characters=100,
        unit_prices={"credit_multiplier": 2.0, "usd_per_credit": 0.000198},
    )
    assert cost == pytest.approx(100 * 2.0 * 0.000198)


def test_imagen_cost_per_image() -> None:
    cost = pricing.compute_imagen_cost(
        images=3,
        unit_prices={"usd_per_image": 0.04},
    )
    assert cost == pytest.approx(0.12)


def test_kling_cost_per_second() -> None:
    cost = pricing.compute_kling_cost(
        duration_sec=5,
        unit_prices={"usd_per_sec": 0.084},
    )
    assert cost == pytest.approx(0.42)


def test_sync_cost_per_second() -> None:
    cost = pricing.compute_sync_cost(
        duration_sec=10,
        unit_prices={"usd_per_sec": 0.05},
    )
    assert cost == pytest.approx(0.5)


def test_kling_billed_duration_within_first_bucket() -> None:
    assert pricing.kling_billed_duration(3.5, [5, 10]) == 5


def test_kling_billed_duration_exact_bucket() -> None:
    assert pricing.kling_billed_duration(5.0, [5, 10]) == 5


def test_kling_billed_duration_overflow_to_next_bucket() -> None:
    assert pricing.kling_billed_duration(6.0, [5, 10]) == 10


def test_kling_billed_duration_caps_at_max_bucket() -> None:
    assert pricing.kling_billed_duration(15.0, [5, 10]) == 10


def test_kling_billed_duration_empty_buckets_uses_ceil() -> None:
    assert pricing.kling_billed_duration(4.2, []) == 5
    assert pricing.kling_billed_duration(0.5, []) == 1


def test_usd_to_jpy() -> None:
    assert pricing.usd_to_jpy(1.0, 150.0) == 150.0
    assert pricing.usd_to_jpy(2.5, 145.0) == pytest.approx(362.5)


def test_gemini_text_cost_input_only() -> None:
    cost = pricing.compute_gemini_text_cost(
        input_tokens=1_000_000,
        output_tokens=0,
        unit_prices={"input_per_mtok": 1.25, "output_per_mtok": 5.0},
    )
    assert cost == pytest.approx(1.25)


def test_gemini_text_cost_output_only() -> None:
    cost = pricing.compute_gemini_text_cost(
        input_tokens=0,
        output_tokens=1_000_000,
        unit_prices={"input_per_mtok": 1.25, "output_per_mtok": 5.0},
    )
    assert cost == pytest.approx(5.0)


def test_gemini_text_cost_combined_realistic() -> None:
    """analyze dialogue rewrite の典型コスト (~3K input + 3K output)。"""
    cost = pricing.compute_gemini_text_cost(
        input_tokens=3000,
        output_tokens=3000,
        unit_prices={"input_per_mtok": 1.25, "output_per_mtok": 5.0},
    )
    # 3000 × 1.25/M + 3000 × 5/M = 0.00375 + 0.015 = 0.01875
    assert cost == pytest.approx(0.01875)
