"""cost_tracking.recorder の単体テスト (各 stage 用 facade)。"""
from __future__ import annotations

import json

import pytest

from cost_tracking import recorder, records


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """pricebook と cost_records をテスト用の一時パスに差し替える。"""
    book = {
        "version": 1,
        "jpy_per_usd": 150.0,
        "providers": {
            "anthropic": {"claude-opus-4-7": {"input_per_mtok": 15.0, "output_per_mtok": 75.0}},
            "elevenlabs": {"eleven_v3": {"credit_multiplier": 2.0, "usd_per_credit": 0.000198}},
            "google": {
                "imagen-3.0": {"usd_per_image": 0.04},
                "gemini-2.5-pro": {
                    "input_per_mtok": 1.25, "output_per_mtok": 5.0,
                },
                "gemini-2.5-flash": {
                    "input_per_mtok": 0.3, "output_per_mtok": 2.5,
                },
            },
            "fal": {"kling-v3-pro": {"usd_per_sec": 0.084, "billing_buckets": [5, 10]}},
            "sync": {"lipsync-2": {"usd_per_sec": 0.05}},
        },
    }
    pb_path = tmp_path / "pricebook.json"
    pb_path.write_text(json.dumps(book), encoding="utf-8")
    monkeypatch.setenv("PRICEBOOK_PATH", str(pb_path))

    rec_path = tmp_path / "cost_records.jsonl"
    monkeypatch.setenv("COST_RECORDS_PATH", str(rec_path))
    return rec_path


def test_record_analyze_persists_and_returns(isolated) -> None:
    rec = recorder.record_analyze(
        project_ts="20260506_120000",
        model="claude-opus-4-7",
        input_tokens=200_000,
        output_tokens=12_000,
    )
    assert rec.stage == "analyze"
    assert rec.provider == "anthropic"
    assert rec.units["input_tokens"] == 200_000
    assert rec.cost_usd == pytest.approx((200_000 * 15.0 + 12_000 * 75.0) / 1_000_000)
    persisted = list(records.iter_all())
    assert len(persisted) == 1
    assert persisted[0].record_id == rec.record_id


def test_record_dialogue_rewrite_persists(isolated) -> None:
    """analyze dialogue rewrite phase の cost が gemini-2.5-pro 単価で
    `analyze_rewrite` stage として記録される。"""
    rec = recorder.record_dialogue_rewrite(
        project_ts="20260517_120000",
        model="gemini-2.5-pro",
        input_tokens=3000,
        output_tokens=3000,
        metadata={"status": "success"},
    )
    assert rec.stage == "analyze_rewrite"
    assert rec.provider == "google"
    assert rec.units["input_tokens"] == 3000
    assert rec.units["output_tokens"] == 3000
    # 3000 × 1.25/M + 3000 × 5/M = 0.01875
    assert rec.cost_usd == pytest.approx(0.01875)
    assert rec.metadata["status"] == "success"
    persisted = list(records.iter_all())
    assert len(persisted) == 1
    assert persisted[0].record_id == rec.record_id


def test_record_dialogue_rewrite_flash_model(isolated) -> None:
    """gemini-2.5-flash で同じ tokens の cost が安くなる。"""
    rec = recorder.record_dialogue_rewrite(
        project_ts="20260517_120000",
        model="gemini-2.5-flash",
        input_tokens=3000,
        output_tokens=3000,
    )
    # 3000 × 0.3/M + 3000 × 2.5/M = 0.0009 + 0.0075 = 0.0084
    assert rec.cost_usd == pytest.approx(0.0084)


def test_record_tts_uses_elevenlabs_pricing(isolated) -> None:
    rec = recorder.record_tts(
        project_ts="20260506_120000",
        model="eleven_v3",
        characters=100,
        scene_index=0,
        line_index=2,
    )
    assert rec.stage == "tts"
    assert rec.provider == "elevenlabs"
    assert rec.scene_index == 0
    assert rec.line_index == 2
    assert rec.cost_usd == pytest.approx(100 * 2.0 * 0.000198)


def test_record_imagen_default_image_count(isolated) -> None:
    rec = recorder.record_imagen(
        project_ts="20260506_120000",
        model="imagen-3.0",
        scene_index=3,
    )
    assert rec.stage == "bg"
    assert rec.provider == "google"
    assert rec.units["images"] == 1.0
    assert rec.cost_usd == pytest.approx(0.04)


def test_record_kling_uses_fal_pricing(isolated) -> None:
    rec = recorder.record_kling(
        project_ts="20260506_120000",
        model="kling-v3-pro",
        duration_sec=5,
        scene_index=2,
    )
    assert rec.stage == "kling"
    assert rec.provider == "fal"
    assert rec.cost_usd == pytest.approx(0.42)


def test_record_lipsync_uses_sync_pricing(isolated) -> None:
    rec = recorder.record_lipsync(
        project_ts="20260506_120000",
        model="lipsync-2",
        duration_sec=10,
        scene_index=1,
    )
    assert rec.stage == "lipsync"
    assert rec.provider == "sync"
    assert rec.cost_usd == pytest.approx(0.5)


def test_record_operation_can_be_regenerate(isolated) -> None:
    rec = recorder.record_kling(
        project_ts="20260506_120000",
        model="kling-v3-pro",
        duration_sec=5,
        scene_index=2,
        operation="regenerate",
    )
    assert rec.operation == "regenerate"


def test_record_metadata_is_persisted(isolated) -> None:
    rec = recorder.record_kling(
        project_ts="20260506_120000",
        model="kling-v3-pro",
        duration_sec=5,
        metadata={"request_id": "abc-123", "retry_count": 2},
    )
    assert rec.metadata == {"request_id": "abc-123", "retry_count": 2}
    persisted = list(records.iter_all())
    assert persisted[0].metadata == {"request_id": "abc-123", "retry_count": 2}


def test_record_unknown_model_raises_keyerror(isolated) -> None:
    with pytest.raises(KeyError, match="unknown model"):
        recorder.record_tts(
            project_ts=None,
            model="eleven_unknown_v9",
            characters=10,
        )


def test_records_are_isolated_per_call(isolated) -> None:
    recorder.record_imagen(project_ts="A", model="imagen-3.0", scene_index=0)
    recorder.record_imagen(project_ts="A", model="imagen-3.0", scene_index=1)
    recorder.record_imagen(project_ts="B", model="imagen-3.0", scene_index=0)
    a_records = list(records.iter_filtered(project_ts="A"))
    b_records = list(records.iter_filtered(project_ts="B"))
    assert len(a_records) == 2
    assert len(b_records) == 1
