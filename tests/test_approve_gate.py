"""Phase 4: scripts/approve_gate のテスト。"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setattr("config.BASE_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr("config.SLACK_WEBHOOK_URL", "")
    from analytics import db as _db
    _db.init_db()
    return _db


def _make_awaiting(db, ts: str) -> None:
    db.append_stage_run(
        ts=ts, stage="publish",
        started_at="2026-05-09T00:00:00+00:00",
        ended_at="2026-05-09T00:01:00+00:00",
        status="completed",
    )
    db.update_generation_record(ts, status="awaiting_human_gate")


def test_list_awaiting_returns_only_awaiting(isolated):
    db = isolated
    _make_awaiting(db, "ts_A")
    db.append_stage_run(
        ts="ts_B", stage="publish",
        started_at="2026-05-09T00:00:00+00:00",
        ended_at="2026-05-09T00:01:00+00:00",
        status="completed",
    )

    from scripts import approve_gate
    rows = approve_gate.list_awaiting()
    ts_set = {r["ts"] for r in rows}
    assert "ts_A" in ts_set
    assert "ts_B" not in ts_set


def test_approve_and_publish_invokes_publish(isolated):
    db = isolated
    _make_awaiting(db, "ts_pub")

    from scripts import approve_gate
    fake_result = {"video_id": "vidXYZ", "url": "https://y.t/abc"}
    with patch("final_import.publish.publish",
               return_value=fake_result) as mock_pub:
        result = approve_gate.approve_and_publish("ts_pub", privacy="unlisted")
    mock_pub.assert_called_once_with("ts_pub", "youtube", privacy="unlisted")
    assert result == fake_result
    # generation_record が completed に進む
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM generation_records WHERE ts = ?",
            ("ts_pub",),
        ).fetchone()
    assert row["status"] == "completed"


def test_approve_unknown_ts_raises(isolated):
    from scripts import approve_gate
    with pytest.raises(ValueError, match="awaiting_human_gate"):
        approve_gate.approve_and_publish("ts_does_not_exist")


def test_reject_marks_auto_rejected(isolated):
    db = isolated
    _make_awaiting(db, "ts_rej")
    from scripts import approve_gate
    approve_gate.reject("ts_rej", reason="bad audio")
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM generation_records WHERE ts = ?",
            ("ts_rej",),
        ).fetchone()
    assert row["status"] == "auto_rejected"


def test_reject_unknown_ts_raises(isolated):
    from scripts import approve_gate
    with pytest.raises(ValueError, match="awaiting_human_gate"):
        approve_gate.reject("ts_does_not_exist")
