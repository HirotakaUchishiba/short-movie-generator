"""cost_tracking.report の単体テスト (ProjectReport / OverallReport の集約)。"""
from __future__ import annotations

import json

import pytest

from cost_tracking import recorder, report


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


def test_empty_project_report(isolated) -> None:
    r = report.report_for_project("UNKNOWN_TS")
    assert r.project_ts == "UNKNOWN_TS"
    assert r.record_count == 0
    assert r.total_usd == 0.0
    assert r.per_stage == {}


def test_project_report_sums_per_stage(isolated) -> None:
    ts = "20260506_120000"
    recorder.record_imagen(project_ts=ts, model="imagen-3.0", scene_index=0)
    recorder.record_imagen(project_ts=ts, model="imagen-3.0", scene_index=1)
    recorder.record_kling(project_ts=ts, model="kling-v3-pro", duration_sec=5, scene_index=0)
    recorder.record_lipsync(project_ts=ts, model="lipsync-2", duration_sec=10, scene_index=0)

    r = report.report_for_project(ts)
    assert r.record_count == 4
    expected_total = 0.04 + 0.04 + (5 * 0.084) + (10 * 0.05)
    assert r.total_usd == pytest.approx(expected_total)
    assert r.total_jpy == pytest.approx(expected_total * 150.0)
    assert r.per_stage["bg"] == pytest.approx(0.08)
    assert r.per_stage["kling"] == pytest.approx(0.42)
    assert r.per_stage["lipsync"] == pytest.approx(0.5)


def test_project_report_sums_per_scene(isolated) -> None:
    ts = "20260506_120000"
    recorder.record_imagen(project_ts=ts, model="imagen-3.0", scene_index=0)
    recorder.record_kling(project_ts=ts, model="kling-v3-pro", duration_sec=5, scene_index=0)
    recorder.record_imagen(project_ts=ts, model="imagen-3.0", scene_index=1)

    r = report.report_for_project(ts)
    assert r.per_scene[0] == pytest.approx(0.04 + 0.42)
    assert r.per_scene[1] == pytest.approx(0.04)


def test_project_report_excludes_other_projects(isolated) -> None:
    recorder.record_imagen(project_ts="A", model="imagen-3.0", scene_index=0)
    recorder.record_imagen(project_ts="B", model="imagen-3.0", scene_index=0)

    r = report.report_for_project("A")
    assert r.record_count == 1


def test_project_report_per_provider(isolated) -> None:
    ts = "T"
    recorder.record_imagen(project_ts=ts, model="imagen-3.0", scene_index=0)
    recorder.record_tts(project_ts=ts, model="eleven_v3", characters=100, scene_index=0)

    r = report.report_for_project(ts)
    assert "google" in r.per_provider
    assert "elevenlabs" in r.per_provider


def test_overall_report_aggregates_projects(isolated) -> None:
    recorder.record_imagen(project_ts="A", model="imagen-3.0", scene_index=0)
    recorder.record_imagen(project_ts="A", model="imagen-3.0", scene_index=1)
    recorder.record_imagen(project_ts="B", model="imagen-3.0", scene_index=0)

    r = report.report_overall()
    assert r.project_count == 2
    assert r.record_count == 3
    assert r.per_project["A"] == pytest.approx(0.08)
    assert r.per_project["B"] == pytest.approx(0.04)


def test_overall_report_filters_by_since(isolated) -> None:
    recorder.record_imagen(project_ts="A", model="imagen-3.0", scene_index=0)
    # 1 件目を読み出して timestamp 取得 → since にして 1 件目だけ拾う条件を作る
    from cost_tracking import records as recs_mod
    first = list(recs_mod.iter_all())[0]
    recorder.record_imagen(project_ts="B", model="imagen-3.0", scene_index=0)

    r = report.report_overall(since=first.timestamp)
    # 2 件以上 (>= since)。先頭は同 timestamp も含むので 2 件。
    assert r.record_count >= 1


def test_build_project_report_is_pure(isolated) -> None:
    """純粋関数: 同じ入力なら同じ出力 (timestamp 以外)。"""
    from cost_tracking import records as recs_mod
    recorder.record_imagen(project_ts="X", model="imagen-3.0", scene_index=0)
    recs = list(recs_mod.iter_filtered(project_ts="X"))
    r1 = report.build_project_report("X", recs, 150.0)
    r2 = report.build_project_report("X", recs, 150.0)
    assert r1.total_usd == r2.total_usd
    assert r1.per_stage == r2.per_stage
