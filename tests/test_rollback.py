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
    """idempotent seed: screenplay + video + post 1 件。

    test_rollback_filter_by_platform で同じ video_id を複数 platform で
    seed するため、screenplay / video は INSERT OR IGNORE で再 insert しない。
    """
    sp_id = "sp1"
    with db.get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO screenplays (id, path, name, sha256,
               created_at, raw_json)
               VALUES (?, '/x', 'x', 'sha1', datetime('now'), '{}')""",
            (sp_id,),
        )
        conn.execute(
            """INSERT OR IGNORE INTO videos (id, screenplay_id, output_path,
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


def test_rollback_youtube_marks_post_in_db(isolated):
    """YouTube rollback 成功で posts.rollback_at が埋まり v_active_posts から消える。"""
    db = isolated
    _seed(db, video_id="vid_yt_marked", platform="youtube",
          platform_post_id="abc456")
    # 取り下げ前は v_active_posts に存在
    assert any(p["video_id"] == "vid_yt_marked"
               for p in db.list_active_posts(platform="youtube"))

    from scripts import rollback as rb
    with patch.object(rb, "rollback_youtube", return_value={"id": "abc456"}):
        rb.rollback_video("vid_yt_marked")

    # 取り下げ後は v_active_posts から消える
    assert not any(p["video_id"] == "vid_yt_marked"
                   for p in db.list_active_posts(platform="youtube"))
    # ただし posts table 直接 select すると残っている (= soft delete)
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT rollback_at, rollback_reason FROM posts "
            "WHERE video_id = ?",
            ("vid_yt_marked",),
        ).fetchone()
    assert row["rollback_at"] is not None
    assert row["rollback_reason"] == "cli_rollback_youtube"


def test_rollback_instagram_does_not_mark_db(isolated):
    """IG/TikTok は手動削除なので posts.rollback_at は触らない。"""
    db = isolated
    _seed(db, video_id="vid_ig_unmark", platform="instagram",
          platform_post_id="ig_99")
    from scripts import rollback as rb
    rb.rollback_video("vid_ig_unmark")
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT rollback_at FROM posts WHERE video_id = ?",
            ("vid_ig_unmark",),
        ).fetchone()
    assert row["rollback_at"] is None  # DB は触られていない
    # かつ v_active_posts には残っている
    assert any(p["video_id"] == "vid_ig_unmark"
               for p in db.list_active_posts())
