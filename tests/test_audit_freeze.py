"""Phase 4: scripts/audit_freeze の書き出しテスト。"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setattr("config.BASE_DIR", str(tmp_path), raising=False)
    from analytics import db as _db
    _db.init_db()
    return tmp_path, _db


def test_freeze_writes_jsonl_per_table(isolated):
    tmp_path, db = isolated
    db.append_stage_run(
        ts="t1", stage="script", started_at="x", ended_at="y",
        status="completed",
    )
    db.insert_qa_failure(ts="t1", stage="bg", source="human_reject",
                         tags=[])
    db.insert_experiment_assignment(
        video_id="t1", axis="hook_type", selected_value="共感型",
        strategy="active_explore",
    )

    from scripts.audit_freeze import freeze_tables
    out_dir = tmp_path / "freeze"
    counts = freeze_tables(out_dir)
    assert counts["generation_records"] == 1
    assert counts["qa_failures"] == 1
    assert counts["experiment_assignments"] == 1
    assert (out_dir / "_metadata.json").exists()
    # JSONL parse できる
    rows = [json.loads(line) for line
            in (out_dir / "qa_failures.jsonl").read_text().splitlines()]
    assert rows[0]["source"] == "human_reject"


def test_freeze_with_since_filter(isolated):
    tmp_path, db = isolated
    db.append_stage_run(
        ts="old_t", stage="script", started_at="x", ended_at="y",
        status="completed",
    )
    # since が未来日付 → 何も入らない
    from scripts.audit_freeze import freeze_tables
    out_dir = tmp_path / "freeze_future"
    counts = freeze_tables(out_dir, since="2099-01-01")
    assert counts["generation_records"] == 0


def test_freeze_metadata_records_schema_version(isolated):
    tmp_path, db = isolated
    from scripts.audit_freeze import freeze_tables
    out_dir = tmp_path / "freeze_meta"
    freeze_tables(out_dir)
    meta = json.loads((out_dir / "_metadata.json").read_text())
    assert meta["schema_version"] == db.CURRENT_SCHEMA_VERSION
    assert "frozen_at" in meta
    assert "row_counts" in meta
