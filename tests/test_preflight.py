"""preflight の env / config 検査をカバー。"""

import pytest

import config
import preflight


def test_check_tts_raises_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", None)
    with pytest.raises(preflight.PreflightError) as exc:
        preflight.check_tts()
    assert "ELEVENLABS_API_KEY" in str(exc.value)


def test_check_tts_passes_when_key_set(monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", "fake-key")
    preflight.check_tts()  # 例外が出なければ成功


def test_check_bg_raises_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_API_KEY", None)
    with pytest.raises(preflight.PreflightError):
        preflight.check_bg()


def test_check_kling_raises_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "FAL_API_KEY", None)
    with pytest.raises(preflight.PreflightError) as exc:
        preflight.check_kling()
    assert "FAL_KEY" in str(exc.value)


def test_check_scene_syncso_requires_sync_key(monkeypatch):
    monkeypatch.setattr(config, "LIPSYNC_PROVIDER", "syncso", raising=False)
    monkeypatch.setattr(config, "SYNCSO_API_KEY", None)
    with pytest.raises(preflight.PreflightError) as exc:
        preflight.check_scene()
    assert "SYNC_API_KEY" in str(exc.value)


def test_check_scene_falsync_requires_fal_key(monkeypatch):
    monkeypatch.setattr(config, "LIPSYNC_PROVIDER", "fal-sync", raising=False)
    monkeypatch.setattr(config, "FAL_API_KEY", None)
    with pytest.raises(preflight.PreflightError) as exc:
        preflight.check_scene()
    assert "FAL_KEY" in str(exc.value)


def test_check_scene_domoai_requires_domoai_key(monkeypatch):
    monkeypatch.setattr(config, "LIPSYNC_PROVIDER", "domoai", raising=False)
    monkeypatch.setattr(config, "DOMOAI_API_KEY", None)
    with pytest.raises(preflight.PreflightError) as exc:
        preflight.check_scene()
    assert "DOMOAI_API_KEY" in str(exc.value)


def test_check_scene_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(config, "LIPSYNC_PROVIDER", "bogus", raising=False)
    with pytest.raises(preflight.PreflightError) as exc:
        preflight.check_scene()
    assert "未知" in str(exc.value)


def test_check_scene_skipped_when_lipsync_disabled(monkeypatch):
    monkeypatch.setattr(config, "LIPSYNC_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "SYNCSO_API_KEY", None)
    preflight.check_scene()  # disabled なので key 不在でも通る


def test_check_publish_youtube_lists_missing(monkeypatch):
    for k in ("YOUTUBE_OAUTH_CLIENT_ID", "YOUTUBE_OAUTH_CLIENT_SECRET",
              "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(preflight.PreflightError) as exc:
        preflight.check_publish_youtube()
    msg = str(exc.value)
    assert "YOUTUBE_OAUTH_CLIENT_ID" in msg
    assert "YOUTUBE_OAUTH_CLIENT_SECRET" in msg
    assert "YOUTUBE_REFRESH_TOKEN" in msg


def test_check_publish_youtube_passes_when_all_set(monkeypatch):
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "x")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "x")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "x")
    preflight.check_publish_youtube()


def test_check_stage_dispatch(monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", None)
    with pytest.raises(preflight.PreflightError):
        preflight.check_stage("tts")


def test_check_stage_unknown_is_noop():
    preflight.check_stage("script")  # mapping 外: 何もしない
    preflight.check_stage("overlay")


def test_check_final_import_raises_when_ffmpeg_missing(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda _b: None)
    with pytest.raises(preflight.PreflightError) as exc:
        preflight.check_final_import()
    msg = str(exc.value)
    assert "ffmpeg" in msg
    assert "ffprobe" in msg


def test_check_final_import_raises_lists_only_missing(monkeypatch):
    monkeypatch.setattr(
        preflight.shutil, "which",
        lambda b: "/usr/bin/ffmpeg" if b == "ffmpeg" else None,
    )
    with pytest.raises(preflight.PreflightError) as exc:
        preflight.check_final_import()
    msg = str(exc.value)
    assert "ffprobe" in msg
    assert "ffmpeg," not in msg


def test_check_final_import_passes_when_both_present(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda b: f"/usr/bin/{b}")
    preflight.check_final_import()


def test_check_publish_instagram_phase1_noop(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("INSTAGRAM_BUSINESS_ID", raising=False)
    preflight.check_publish_instagram()


def test_check_publish_tiktok_phase1_noop(monkeypatch):
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TIKTOK_OPEN_ID", raising=False)
    preflight.check_publish_tiktok()


def test_check_stage_final_import_dispatch(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda _b: None)
    with pytest.raises(preflight.PreflightError):
        preflight.check_stage("final_import")
