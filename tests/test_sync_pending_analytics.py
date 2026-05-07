"""scripts/sync_pending_analytics.py の queue 消費フロー."""

import json
from pathlib import Path


def _seed_screenplay_and_video(tmp_path, monkeypatch, ts: str) -> None:
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    sp_path = tmp_path / "sp.json"
    sp_path.write_text(json.dumps({
        "caption": "x", "scenes": [{"lines": [{"text": "a"}]}],
    }), encoding="utf-8")
    from analytics import db as _db
    _db.init_db()
    sp_id = _db.upsert_screenplay(str(sp_path))
    _db.insert_video(video_id=ts, screenplay_id=sp_id,
                     output_path=str(tmp_path / "out.mp4"))


def test_sync_consumes_3_entries_and_keeps_failing_one(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "ANALYTICS_PENDING_PATH", str(tmp_path / "analytics_pending.jsonl"),
    )
    ts = "20260507_100000"
    _seed_screenplay_and_video(tmp_path, monkeypatch, ts)

    from analytics import pending_queue, db as analytics_db
    for pid in ("p_ok1", "p_fail", "p_ok2"):
        pending_queue.append({
            "ts": ts, "platform": "youtube",
            "platform_post_id": pid,
            "url": f"https://x/{pid}",
            "posted_at": "2026-05-07T00:00:00",
            "caption": "c", "hashtags": ["t"],
        })

    real_register = analytics_db.register_post

    def picky(*args, **kwargs):
        if kwargs.get("platform_post_id") == "p_fail":
            raise RuntimeError("still down")
        return real_register(*args, **kwargs)

    monkeypatch.setattr(analytics_db, "register_post", picky)

    from scripts import sync_pending_analytics
    success, failed = sync_pending_analytics.sync()

    assert success == 2
    assert failed == 1

    remaining = pending_queue.read_all()
    assert len(remaining) == 1
    assert remaining[0]["platform_post_id"] == "p_fail"

    posts = analytics_db.list_active_posts(platform="youtube")
    pids = {p["platform_post_id"] for p in posts}
    assert pids == {"p_ok1", "p_ok2"}


def test_sync_empty_queue_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "ANALYTICS_PENDING_PATH", str(tmp_path / "analytics_pending.jsonl"),
    )
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))

    from scripts import sync_pending_analytics
    success, failed = sync_pending_analytics.sync()
    assert success == 0
    assert failed == 0

    assert not Path(tmp_path / "analytics_pending.jsonl").exists()
