"""IG mode=api 経路のテスト (= temp_hosting + Graph API mock)。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setattr("config.BASE_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path / "temp"))
    (tmp_path / "temp").mkdir()
    return tmp_path


def test_is_api_mode_default_false(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_PUBLISH_MODE", raising=False)
    from final_import import publish
    assert publish._is_api_mode("INSTAGRAM_PUBLISH_MODE") is False


def test_is_api_mode_true_when_env_set(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_PUBLISH_MODE", "api")
    from final_import import publish
    assert publish._is_api_mode("INSTAGRAM_PUBLISH_MODE") is True


def test_publish_instagram_api_calls_upload_and_records(isolated, monkeypatch):
    from final_import import publish
    from platform_clients import instagram

    fake_video = isolated / "v.mp4"
    fake_video.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 200)

    fake_upload = MagicMock(return_value={
        "video_id": "ig_media_123",
        "url": "https://instagram.com/reel/ig_media_123/",
        "raw_response": {"id": "ig_media_123"},
    })
    monkeypatch.setattr(instagram, "upload_video", fake_upload)

    # analytics db への register_post を成功させるためのスタブ
    monkeypatch.setattr(
        publish, "_ensure_video_in_analytics", lambda ts, video: None,
    )
    fake_register = MagicMock()
    monkeypatch.setattr(
        "analytics.db.register_post", fake_register,
    )
    monkeypatch.setattr("analytics.db.init_db", lambda: None)

    result = publish._publish_instagram_api(
        ts="20260509_120000",
        video=fake_video,
        title="Hello",
        description="some body",
        tags=["foo", "bar"],
    )

    fake_upload.assert_called_once()
    _, kwargs = fake_upload.call_args
    assert kwargs["file_path"] == fake_video
    assert "#foo" in kwargs["caption"] and "#bar" in kwargs["caption"]
    assert "some body" in kwargs["caption"]

    assert result["platform"] == "instagram"
    assert result["video_id"] == "ig_media_123"
    assert result["url"] == "https://instagram.com/reel/ig_media_123/"
    assert result["analytics_persisted"] is True

    fake_register.assert_called_once()
    _, regkw = fake_register.call_args
    assert regkw["platform"] == "instagram"
    assert regkw["platform_post_id"] == "ig_media_123"


def _setup_dispatch_project(isolated, ts: str) -> None:
    """publish() のディスパッチが video / caption を読みに行ける最小プロジェクトを作る。"""
    import json
    import progress_store
    ts_dir = isolated / "temp" / ts
    ts_dir.mkdir(parents=True)
    (ts_dir / "metadata.json").write_text(json.dumps({
        "screenplay_name": "x.json",
        "screenplay_path": str(ts_dir / "screenplay.json"),
        "screenplay_sha256": "x" * 64,
        "created_at": "2026-05-09T12:00:00",
    }))
    (ts_dir / "screenplay.json").write_text(json.dumps({
        "caption": "Hello\n\n#tag1",
        "scenes": [],
    }))
    for stage in ("script", "tts", "bg", "kling", "scene", "overlay",
                  "final_import"):
        progress_store.mark_generated(str(ts_dir), stage)
        progress_store.mark_approved(str(ts_dir), stage)
    # canonical_final_path が無ければ pipeline raw (= output/reels_<ts>.mp4) にフォール
    (isolated / "output").mkdir(parents=True, exist_ok=True)
    raw = isolated / "output" / f"reels_{ts}.mp4"
    raw.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
    # post_captions/x.md (= read_post_caption_for_ts が読む)
    captions_dir = isolated / "post_captions"
    captions_dir.mkdir()
    (captions_dir / "x.md").write_text("# title\n\ndesc\n\n#t1\n")


def test_publish_dispatch_uses_api_when_mode_set(isolated, monkeypatch):
    """publish() のディスパッチが INSTAGRAM_PUBLISH_MODE=api で API 経路を呼ぶ。"""
    from final_import import publish

    ts = "20260509_120000"
    _setup_dispatch_project(isolated, ts)
    monkeypatch.setenv("INSTAGRAM_PUBLISH_MODE", "api")
    monkeypatch.setattr("config.OUTPUT_DIR", str(isolated / "output"))
    monkeypatch.setattr("config.POST_CAPTIONS_DIR",
                        str(isolated / "post_captions"))
    fake_api = MagicMock(return_value={
        "platform": "instagram", "video_id": "x",
        "url": "https://x", "manual": False,
    })
    monkeypatch.setattr(publish, "_publish_instagram_api", fake_api)
    fake_semi = MagicMock()
    monkeypatch.setattr(publish, "_publish_semi_auto", fake_semi)
    monkeypatch.setattr(publish, "_existing_successful_publish",
                        lambda *_a, **_kw: None)
    monkeypatch.setattr(publish, "_record_publish", lambda *_a, **_kw: None)
    monkeypatch.setattr(publish.preflight, "check_publish_instagram",
                        lambda: None)

    publish.publish(ts, "instagram")

    fake_api.assert_called_once()
    fake_semi.assert_not_called()


def test_publish_tiktok_api_mode_raises_not_implemented(isolated, monkeypatch):
    """TIKTOK_PUBLISH_MODE=api は scope 申請待ちなので NotImplementedError。"""
    from final_import import publish

    ts = "20260509_130000"
    _setup_dispatch_project(isolated, ts)
    monkeypatch.setenv("TIKTOK_PUBLISH_MODE", "api")
    monkeypatch.setattr("config.OUTPUT_DIR", str(isolated / "output"))
    monkeypatch.setattr("config.POST_CAPTIONS_DIR",
                        str(isolated / "post_captions"))
    monkeypatch.setattr(publish, "_existing_successful_publish",
                        lambda *_a, **_kw: None)

    with pytest.raises(NotImplementedError, match="TIKTOK_PUBLISH_MODE"):
        publish.publish(ts, "tiktok")
