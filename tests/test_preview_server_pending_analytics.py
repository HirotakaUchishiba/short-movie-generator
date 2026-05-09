"""GET /api/analytics/pending と POST /api/analytics/pending/sync のテスト。"""
import json
import os

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    pending_path = tmp_path / "analytics_pending.jsonl"
    monkeypatch.setenv("ANALYTICS_PENDING_PATH", str(pending_path))
    import preview_server
    monkeypatch.setattr(preview_server, "_AUTH_TOKEN", None)
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client(), pending_path


def test_pending_status_empty(client) -> None:
    c, _ = client
    r = c.get("/api/analytics/pending")
    assert r.status_code == 200
    body = r.get_json()
    assert body == {"count": 0, "oldest_at": None}


def test_pending_status_returns_count_and_oldest(client) -> None:
    c, pending_path = client
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    entries = [
        {"ts": "20260101_120000", "platform": "youtube",
         "platform_post_id": "abc", "timestamp": "2026-01-01T12:00:00+00:00"},
        {"ts": "20260101_130000", "platform": "instagram",
         "platform_post_id": "ig1", "timestamp": "2026-01-02T12:00:00+00:00"},
    ]
    with open(pending_path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    r = c.get("/api/analytics/pending")
    body = r.get_json()
    assert body["count"] == 2
    assert body["oldest_at"] == "2026-01-01T12:00:00+00:00"
    assert set(body["platforms"]) == {"youtube", "instagram"}


def test_pending_sync_returns_counts(client, monkeypatch) -> None:
    c, pending_path = client
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pending_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": "20260101_120000",
            "platform": "youtube",
            "platform_post_id": "abc",
            "url": "https://y.t/abc",
            "timestamp": "2026-01-01T12:00:00+00:00",
        }) + "\n")

    # finalize_pending_publish が project metadata 不在で失敗するので no-op に置換
    import final_import.publish as pub
    monkeypatch.setattr(pub, "finalize_pending_publish", lambda ts: False)

    # register_post を成功させるため事前に screenplay → video を入れる
    from analytics import db as adb
    adb.init_db()
    with adb.get_connection() as conn:
        conn.execute(
            "INSERT INTO screenplays(id, path, name, sha256, created_at, raw_json) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            ("x" * 12, "/tmp/x.json", "x.json", "x" * 64,
             "2026-01-01T00:00:00+00:00", "{}"),
        )
        conn.execute(
            "INSERT INTO videos(id, screenplay_id, output_path, generated_at) "
            "VALUES(?, ?, ?, ?)",
            ("20260101_120000", "x" * 12, "/tmp/x.mp4", "2026-01-01T00:00:00+00:00"),
        )

    r = c.post("/api/analytics/pending/sync")
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] >= 1
    # queue が空になる
    r2 = c.get("/api/analytics/pending")
    assert r2.get_json()["count"] == 0
