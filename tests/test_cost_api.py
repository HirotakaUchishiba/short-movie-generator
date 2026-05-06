"""preview_server の /api/cost/* endpoint の単体テスト。"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    book = {
        "version": 1,
        "jpy_per_usd": 145.0,
        "providers": {
            "google": {"imagen-3.0": {"usd_per_image": 0.04}},
            "fal": {"kling-v3-pro": {"usd_per_sec": 0.084, "billing_buckets": [5, 10]}},
            "elevenlabs": {"eleven_v3": {"credit_multiplier": 2.0, "usd_per_credit": 0.000198}},
            "sync": {"lipsync-2": {"usd_per_sec": 0.05}},
            "anthropic": {"claude-opus-4-7": {"input_per_mtok": 15.0, "output_per_mtok": 75.0}},
        },
    }
    pb_path = tmp_path / "pricebook.json"
    pb_path.write_text(json.dumps(book), encoding="utf-8")
    monkeypatch.setenv("PRICEBOOK_PATH", str(pb_path))

    rec_path = tmp_path / "cost_records.jsonl"
    monkeypatch.setenv("COST_RECORDS_PATH", str(rec_path))
    monkeypatch.delenv("JPY_PER_USD", raising=False)

    from preview_server import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _seed_imagen(count: int) -> None:
    from cost_tracking import recorder
    for i in range(count):
        recorder.record_imagen(project_ts=f"P{i}", model="imagen-3.0", scene_index=i)


def test_pricebook_endpoint(client) -> None:
    r = client.get("/api/cost/pricebook")
    assert r.status_code == 200
    j = r.get_json()
    assert "pricebook" in j
    assert j["jpy_per_usd"] == 145.0
    assert "imagen-3.0" in j["pricebook"]["providers"]["google"]


def test_estimate_missing_model_returns_400(client) -> None:
    r = client.get("/api/cost/estimate/bg?image_count=1")
    assert r.status_code == 400
    assert "model required" in r.get_json()["error"]


def test_estimate_unknown_stage_returns_400(client) -> None:
    r = client.get("/api/cost/estimate/unknown_stage?model=x")
    assert r.status_code == 400


def test_estimate_insufficient_history(client) -> None:
    r = client.get("/api/cost/estimate/bg?model=imagen-3.0&image_count=1")
    assert r.status_code == 200
    j = r.get_json()
    assert j["confidence"] == "insufficient"
    assert j["cost_usd"] is None


def test_estimate_history_based(client) -> None:
    _seed_imagen(3)
    r = client.get("/api/cost/estimate/bg?model=imagen-3.0&image_count=2")
    assert r.status_code == 200
    j = r.get_json()
    assert j["confidence"] == "history"
    assert j["cost_usd"] == pytest.approx(0.08)
    assert j["cost_jpy"] == pytest.approx(0.08 * 145.0)


def test_estimate_kling_history(client) -> None:
    from cost_tracking import recorder
    for i in range(3):
        recorder.record_kling(
            project_ts=f"P{i}", model="kling-v3-pro",
            duration_sec=5, scene_index=i,
        )
    r = client.get("/api/cost/estimate/kling?model=kling-v3-pro&duration_sec=10")
    assert r.status_code == 200
    j = r.get_json()
    assert j["confidence"] == "history"
    assert j["cost_usd"] == pytest.approx(10 * 0.084)


def test_report_project_endpoint(client) -> None:
    from cost_tracking import recorder
    recorder.record_imagen(project_ts="X", model="imagen-3.0", scene_index=0)
    recorder.record_imagen(project_ts="X", model="imagen-3.0", scene_index=1)
    r = client.get("/api/cost/report/project/X")
    assert r.status_code == 200
    j = r.get_json()
    assert j["project_ts"] == "X"
    assert j["record_count"] == 2
    assert j["total_usd"] == pytest.approx(0.08)
    assert "bg" in j["per_stage"]


def test_report_project_empty(client) -> None:
    r = client.get("/api/cost/report/project/MISSING")
    assert r.status_code == 200
    j = r.get_json()
    assert j["record_count"] == 0
    assert j["total_usd"] == 0.0


def test_report_overall_endpoint(client) -> None:
    from cost_tracking import recorder
    recorder.record_imagen(project_ts="A", model="imagen-3.0", scene_index=0)
    recorder.record_imagen(project_ts="B", model="imagen-3.0", scene_index=0)
    r = client.get("/api/cost/report")
    assert r.status_code == 200
    j = r.get_json()
    assert j["project_count"] == 2
    assert j["record_count"] == 2


def test_median_endpoint_history(client) -> None:
    _seed_imagen(3)
    r = client.get("/api/cost/median/bg?model=imagen-3.0")
    assert r.status_code == 200
    j = r.get_json()
    assert j["confidence"] == "history"
    assert j["usd_per_unit"] == pytest.approx(0.04)
    assert j["unit_label"] == "image"
    assert j["jpy_per_usd"] == 145.0


def test_median_endpoint_insufficient(client) -> None:
    r = client.get("/api/cost/median/bg?model=imagen-3.0")
    assert r.status_code == 200
    j = r.get_json()
    assert j["confidence"] == "insufficient"
    assert j["usd_per_unit"] is None


def test_median_endpoint_missing_model(client) -> None:
    r = client.get("/api/cost/median/bg")
    assert r.status_code == 400


def test_median_endpoint_unsupported_stage(client) -> None:
    r = client.get("/api/cost/median/analyze?model=claude-opus-4-7")
    assert r.status_code == 400
