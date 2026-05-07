"""Phase 4: scripts/rollback の経路テスト (= 外部 API は mock)。"""
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


def _seed(db, *, video_id: str, platform: str = "youtube",
          platform_post_id: str = "abc"):
    """seed: screenplay + video (なければ) + post 1 件。

    `insert_video` は INSERT OR REPLACE で既存 row を再作成するため、
    関連する posts が ``ON DELETE CASCADE`` で消える。同じ video_id を
    別 platform で seed し直したい場合は重複 insert を避ける。
    """
    sp_id = "sp1"
    with db.get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO screenplays (id, path, name, sha256,
               created_at, raw_json)
               VALUES (?, '/x', 'x', 'sha1', datetime('now'), '{}')""",
            (sp_id,),
        )
        existing = conn.execute(
            "SELECT 1 FROM videos WHERE id = ?", (video_id,),
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO videos (id, screenplay_id, output_path,
                   generated_at)
                   VALUES (?, ?, '/tmp/v.mp4', datetime('now'))""",
                (video_id, sp_id),
            )
    db.register_post(video_id, platform, platform_post_id,
                     url=f"https://yt/watch?v={platform_post_id}")


def test_rollback_youtube_calls_data_api(isolated):
    db = isolated
    _seed(db, video_id="vid1", platform="youtube",
          platform_post_id="abc123")
    from scripts import rollback as rb
    with patch.object(rb, "rollback_youtube", return_value={"id": "abc123"}) as p:
        results = rb.rollback_video("vid1")
    p.assert_called_once_with("abc123")
    assert results["youtube"]["status"] == "private"


def test_rollback_unknown_video_id_raises(isolated):
    from scripts import rollback as rb
    with pytest.raises(ValueError):
        rb.rollback_video("no_such_id")


def test_rollback_instagram_marks_manual_required(isolated):
    db = isolated
    _seed(db, video_id="vid_ig", platform="instagram",
          platform_post_id="ig_post1")
    from scripts import rollback as rb
    results = rb.rollback_video("vid_ig")
    assert results["instagram"]["status"] == "manual_required"


def test_rollback_youtube_failure_records_error(isolated):
    db = isolated
    _seed(db, video_id="vid_fail", platform="youtube",
          platform_post_id="zzz")
    from scripts import rollback as rb
    with patch.object(rb, "rollback_youtube",
                      side_effect=RuntimeError("api 500")):
        results = rb.rollback_video("vid_fail")
    assert results["youtube"]["status"] == "failed"
    assert "api 500" in results["youtube"]["error"]


def test_rollback_filter_by_platform(isolated):
    db = isolated
    _seed(db, video_id="vmix", platform="youtube",
          platform_post_id="yt1")
    _seed(db, video_id="vmix", platform="tiktok",
          platform_post_id="tt1")
    from scripts import rollback as rb
    with patch.object(rb, "rollback_youtube", return_value={}):
        results = rb.rollback_video("vmix", platform="youtube")
    assert "youtube" in results
    assert "tiktok" not in results
