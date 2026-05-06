"""cost_tracking.estimator の単体テスト (履歴 only の動的見積もり)。"""
from __future__ import annotations

import json

import pytest

from cost_tracking import estimator, recorder


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    book = {
        "version": 1,
        "jpy_per_usd": 150.0,
        "providers": {
            "anthropic": {"claude-opus-4-7": {"input_per_mtok": 15.0, "output_per_mtok": 75.0}},
            "elevenlabs": {"eleven_v3": {"credit_multiplier": 2.0, "usd_per_credit": 0.000198}},
            "google": {"imagen-3.0": {"usd_per_image": 0.04}},
            "fal": {"kling-v3-pro": {"usd_per_sec": 0.084, "billing_buckets": [5, 10]}},
            "sync": {"lipsync-2": {"usd_per_sec": 0.05}},
        },
    }
    pb_path = tmp_path / "pricebook.json"
    pb_path.write_text(json.dumps(book), encoding="utf-8")
    monkeypatch.setenv("PRICEBOOK_PATH", str(pb_path))

    rec_path = tmp_path / "cost_records.jsonl"
    monkeypatch.setenv("COST_RECORDS_PATH", str(rec_path))


def _seed_imagen(count: int) -> None:
    for i in range(count):
        recorder.record_imagen(project_ts=f"P{i}", model="imagen-3.0", scene_index=i)


def _seed_tts(count: int, characters: int = 50) -> None:
    for i in range(count):
        recorder.record_tts(
            project_ts=f"P{i}",
            model="eleven_v3",
            characters=characters,
            scene_index=i,
        )


def _seed_kling(count: int, duration_sec: int = 5) -> None:
    for i in range(count):
        recorder.record_kling(
            project_ts=f"P{i}",
            model="kling-v3-pro",
            duration_sec=duration_sec,
            scene_index=i,
        )


def _seed_lipsync(count: int, duration_sec: int = 8) -> None:
    for i in range(count):
        recorder.record_lipsync(
            project_ts=f"P{i}",
            model="lipsync-2",
            duration_sec=duration_sec,
            scene_index=i,
        )


def _seed_analyze(count: int) -> None:
    for i in range(count):
        recorder.record_analyze(
            project_ts=f"P{i}",
            model="claude-opus-4-7",
            input_tokens=200_000,
            output_tokens=12_000,
        )


def test_insufficient_when_no_history(isolated) -> None:
    e = estimator.estimate_imagen(image_count=1, model="imagen-3.0")
    assert e.confidence == "insufficient"
    assert e.cost_usd is None
    assert e.sample_size == 0


def test_insufficient_below_threshold(isolated) -> None:
    _seed_imagen(2)  # MIN_HISTORY_SAMPLES = 3
    e = estimator.estimate_imagen(image_count=1, model="imagen-3.0")
    assert e.confidence == "insufficient"
    assert e.sample_size == 2


def test_history_at_threshold(isolated) -> None:
    _seed_imagen(3)
    e = estimator.estimate_imagen(image_count=2, model="imagen-3.0")
    assert e.confidence == "history"
    assert e.sample_size == 3
    assert e.cost_usd == pytest.approx(2 * 0.04)
    assert e.cost_jpy == pytest.approx(2 * 0.04 * 150.0)


def test_imagen_scales_with_image_count(isolated) -> None:
    _seed_imagen(5)
    e1 = estimator.estimate_imagen(image_count=1, model="imagen-3.0")
    e10 = estimator.estimate_imagen(image_count=10, model="imagen-3.0")
    assert e10.cost_usd == pytest.approx(e1.cost_usd * 10)


def test_tts_uses_per_char_rate(isolated) -> None:
    _seed_tts(3, characters=100)
    e = estimator.estimate_tts(characters=200, model="eleven_v3")
    assert e.confidence == "history"
    expected_per_char = 100 * 2.0 * 0.000198 / 100  # = 2.0 * 0.000198
    assert e.cost_usd == pytest.approx(200 * expected_per_char)


def test_kling_uses_per_sec_rate(isolated) -> None:
    _seed_kling(3, duration_sec=5)
    e = estimator.estimate_kling(duration_sec=10, model="kling-v3-pro")
    assert e.confidence == "history"
    assert e.cost_usd == pytest.approx(10 * 0.084)


def test_lipsync_uses_per_sec_rate(isolated) -> None:
    _seed_lipsync(3, duration_sec=8)
    e = estimator.estimate_lipsync(duration_sec=12, model="lipsync-2")
    assert e.cost_usd == pytest.approx(12 * 0.05)


def test_analyze_uses_unit_prices_median(isolated) -> None:
    _seed_analyze(3)
    e = estimator.estimate_analyze(
        input_tokens=300_000,
        output_tokens=20_000,
        model="claude-opus-4-7",
    )
    assert e.confidence == "history"
    expected = (300_000 * 15.0 + 20_000 * 75.0) / 1_000_000
    assert e.cost_usd == pytest.approx(expected)


def test_estimator_filters_by_model(isolated) -> None:
    """別モデルの履歴は混入しない。"""
    _seed_tts(3, characters=50)
    # 別モデルでは履歴ゼロのまま
    e = estimator.estimate_tts(characters=10, model="eleven_flash_v2_5")
    assert e.confidence == "insufficient"


def test_combine_all_history(isolated) -> None:
    _seed_imagen(3)
    _seed_kling(3)
    e_bg = estimator.estimate_imagen(image_count=2, model="imagen-3.0")
    e_kl = estimator.estimate_kling(duration_sec=10, model="kling-v3-pro")
    total = estimator.combine([("bg", e_bg), ("kling", e_kl)])
    assert total.confidence == "history"
    assert total.cost_usd == pytest.approx(e_bg.cost_usd + e_kl.cost_usd)
    assert total.breakdown == {"bg": e_bg.cost_usd, "kling": e_kl.cost_usd}


def test_combine_partial(isolated) -> None:
    _seed_imagen(3)
    e_bg = estimator.estimate_imagen(image_count=1, model="imagen-3.0")
    e_kl = estimator.estimate_kling(duration_sec=5, model="kling-v3-pro")
    total = estimator.combine([("bg", e_bg), ("kling", e_kl)])
    assert total.confidence == "partial"
    assert total.cost_usd == pytest.approx(e_bg.cost_usd)
    assert "_insufficient" in total.breakdown
    assert "kling" in total.breakdown["_insufficient"]


def test_combine_all_insufficient(isolated) -> None:
    e_bg = estimator.estimate_imagen(image_count=1, model="imagen-3.0")
    e_kl = estimator.estimate_kling(duration_sec=5, model="kling-v3-pro")
    total = estimator.combine([("bg", e_bg), ("kling", e_kl)])
    assert total.confidence == "insufficient"
    assert total.cost_usd is None


def test_jpy_uses_env_override(isolated, monkeypatch) -> None:
    monkeypatch.setenv("JPY_PER_USD", "160")
    _seed_imagen(3)
    e = estimator.estimate_imagen(image_count=1, model="imagen-3.0")
    assert e.cost_jpy == pytest.approx(0.04 * 160)


def test_median_rate_imagen_history(isolated) -> None:
    _seed_imagen(3)
    rate = estimator.median_rate("bg", "imagen-3.0")
    assert rate.confidence == "history"
    assert rate.usd_per_unit == pytest.approx(0.04)
    assert rate.unit_label == "image"
    assert rate.sample_size == 3
    assert rate.jpy_per_usd == 150.0


def test_median_rate_insufficient(isolated) -> None:
    _seed_imagen(2)
    rate = estimator.median_rate("bg", "imagen-3.0")
    assert rate.confidence == "insufficient"
    assert rate.usd_per_unit is None


def test_median_rate_unsupported_stage(isolated) -> None:
    with pytest.raises(ValueError, match="unsupported stage"):
        estimator.median_rate("analyze", "claude-opus-4-7")


def test_median_rate_kling(isolated) -> None:
    _seed_kling(3, duration_sec=5)
    rate = estimator.median_rate("kling", "kling-v3-pro")
    assert rate.confidence == "history"
    assert rate.unit_label == "sec"
    assert rate.usd_per_unit == pytest.approx(0.084)
