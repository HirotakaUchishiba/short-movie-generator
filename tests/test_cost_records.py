"""cost_tracking.records の単体テスト (CostRecord + JSONL 永続化)。"""
from __future__ import annotations

import json

import pytest

from cost_tracking import records


@pytest.fixture
def tmp_records(tmp_path, monkeypatch):
    path = tmp_path / "cost_records.jsonl"
    monkeypatch.setenv("COST_RECORDS_PATH", str(path))
    return path


def _sample_record(**overrides) -> records.CostRecord:
    base = dict(
        project_ts="20260506_120000",
        stage="bg",
        operation="generate",
        provider="google",
        model="imagen-3.0",
        units={"images": 1.0},
        unit_prices={"usd_per_image": 0.04},
        cost_usd=0.04,
        scene_index=0,
    )
    base.update(overrides)
    return records.make_record(**base)


def test_make_record_assigns_uuid_and_timestamp() -> None:
    rec = _sample_record()
    assert rec.record_id
    assert len(rec.record_id) == 36  # uuid4 標準形式
    assert rec.timestamp.endswith("+00:00") or rec.timestamp.endswith("Z")


def test_make_record_rejects_invalid_stage() -> None:
    with pytest.raises(ValueError, match="invalid stage"):
        records.make_record(
            project_ts=None,
            stage="unknown_stage",
            operation="generate",
            provider="x",
            model="y",
            units={},
            unit_prices={},
            cost_usd=0.0,
        )


def test_append_creates_file_with_one_line(tmp_records) -> None:
    rec = _sample_record()
    records.append(rec)
    assert tmp_records.exists()
    lines = tmp_records.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["cost_usd"] == 0.04
    assert obj["provider"] == "google"


def test_append_is_append_only(tmp_records) -> None:
    records.append(_sample_record(scene_index=0))
    records.append(_sample_record(scene_index=1))
    records.append(_sample_record(scene_index=2))
    lines = tmp_records.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_iter_all_yields_appended_records(tmp_records) -> None:
    records.append(_sample_record(scene_index=0))
    records.append(_sample_record(scene_index=1, stage="kling", model="kling-v3-pro"))
    out = list(records.iter_all())
    assert len(out) == 2
    assert out[0].scene_index == 0
    assert out[1].stage == "kling"


def test_iter_all_returns_empty_when_file_missing(tmp_records) -> None:
    assert list(records.iter_all()) == []


def test_iter_filtered_by_project_ts(tmp_records) -> None:
    records.append(_sample_record(project_ts="A"))
    records.append(_sample_record(project_ts="B"))
    records.append(_sample_record(project_ts="A"))
    out = list(records.iter_filtered(project_ts="A"))
    assert len(out) == 2
    assert all(r.project_ts == "A" for r in out)


def test_iter_filtered_by_stage_and_provider(tmp_records) -> None:
    records.append(_sample_record(stage="bg", provider="google"))
    records.append(_sample_record(stage="kling", provider="fal", model="kling-v3-pro"))
    records.append(_sample_record(stage="tts", provider="elevenlabs", model="eleven_v3"))
    out = list(records.iter_filtered(stage="kling"))
    assert len(out) == 1
    assert out[0].stage == "kling"
    out = list(records.iter_filtered(provider="elevenlabs"))
    assert len(out) == 1
    assert out[0].provider == "elevenlabs"


def test_iter_filtered_no_filter_returns_all(tmp_records) -> None:
    records.append(_sample_record())
    records.append(_sample_record(stage="tts", provider="elevenlabs", model="eleven_v3"))
    assert len(list(records.iter_filtered())) == 2


def test_make_record_freezes_units_and_unit_prices() -> None:
    units = {"images": 1.0}
    prices = {"usd_per_image": 0.04}
    rec = _sample_record(units=units, unit_prices=prices)
    units["images"] = 999.0
    prices["usd_per_image"] = 999.0
    assert rec.units["images"] == 1.0
    assert rec.unit_prices["usd_per_image"] == 0.04
