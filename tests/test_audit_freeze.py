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


# ─── rotate_old_freezes ──────────────


def test_rotate_archives_old_freezes_and_deletes_originals(tmp_path):
    """N 日経過した freeze を月別 tar.gz に固めて元 dir を削除する。"""
    from datetime import datetime, timezone
    from scripts.audit_freeze import rotate_old_freezes

    base = tmp_path / "audit_freezes"
    base.mkdir()
    # 100 日前の 2 件 (2026-01)
    old1 = base / "2026-01-15_120000"
    old1.mkdir()
    (old1 / "data.jsonl").write_text("a\n")
    old2 = base / "2026-01-20_080000"
    old2.mkdir()
    (old2 / "data.jsonl").write_text("b\n")
    # 30 日前 (= 90 日経過していない、保持される想定)
    recent = base / "2026-04-01_000000"
    recent.mkdir()
    (recent / "data.jsonl").write_text("c\n")

    now = datetime(2026, 5, 9, tzinfo=timezone.utc)
    result = rotate_old_freezes(base, rotate_after_days=90, now=now)
    assert result["archived"] == 2
    assert result["deleted"] == 2
    assert not old1.exists()
    assert not old2.exists()
    assert recent.exists()  # 保持
    archive = base / "_archive" / "2026-01.tar.gz"
    assert archive.exists()


def test_rotate_skips_unparseable_dir_names(tmp_path):
    from datetime import datetime, timezone
    from scripts.audit_freeze import rotate_old_freezes

    base = tmp_path / "audit_freezes"
    base.mkdir()
    weird = base / "manual_backup"
    weird.mkdir()
    (weird / "x.txt").write_text("y")

    now = datetime(2026, 5, 9, tzinfo=timezone.utc)
    result = rotate_old_freezes(base, rotate_after_days=30, now=now)
    assert result["skipped"] == 1
    assert weird.exists()


def test_rotate_handles_multiple_archives_for_same_month(tmp_path):
    """既に 2026-01.tar.gz が存在する場合 2026-01_2.tar.gz として作る。"""
    from datetime import datetime, timezone
    from scripts.audit_freeze import rotate_old_freezes

    base = tmp_path / "audit_freezes"
    archive_dir = base / "_archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "2026-01.tar.gz").write_bytes(b"existing")

    old = base / "2026-01-30_010101"
    old.mkdir()
    (old / "x.jsonl").write_text("d\n")

    now = datetime(2026, 5, 9, tzinfo=timezone.utc)
    rotate_old_freezes(base, rotate_after_days=30, now=now)
    assert (archive_dir / "2026-01.tar.gz").exists()  # 既存維持
    assert (archive_dir / "2026-01_2.tar.gz").exists()  # 新規


def test_rotate_returns_zeros_when_base_dir_missing(tmp_path):
    from scripts.audit_freeze import rotate_old_freezes

    base = tmp_path / "does_not_exist"
    result = rotate_old_freezes(base, rotate_after_days=30)
    assert result == {"archived": 0, "deleted": 0, "skipped": 0}
