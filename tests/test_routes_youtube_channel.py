"""routes/final_publish.py の新エンドポイント /api/youtube/profiles および
/api/youtube/channel-info の挙動テスト。
"""
from unittest.mock import patch

import pytest


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("DISABLE_FINAL_WATCHER", "1")
    import preview_server
    preview_server.app.testing = True
    return preview_server.app


def _client(app):
    return app.test_client()


def test_profiles_returns_default_when_legacy_env_set(app, monkeypatch):
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "rtok")
    for k in list(__import__("os").environ.keys()):
        if k.startswith("YOUTUBE_OAUTH_CLIENT_ID_"):
            monkeypatch.delenv(k, raising=False)
    r = _client(app).get("/api/youtube/profiles")
    assert r.status_code == 200
    assert r.get_json()["profiles"] == ["default"]


def test_profiles_lists_suffixed_envs(app, monkeypatch):
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "rtok")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID_BRAND", "cid-brand")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET_BRAND", "csec-brand")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN_BRAND", "rtok-brand")
    r = _client(app).get("/api/youtube/profiles")
    assert r.status_code == 200
    profiles = r.get_json()["profiles"]
    assert "default" in profiles
    assert "BRAND" in profiles


def test_profiles_skips_partial_suffix_envs(app, monkeypatch):
    """secret/refresh_token が揃っていない suffix 付き env は profiles に出ない。"""
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "rtok")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID_BROKEN", "cid")
    monkeypatch.delenv("YOUTUBE_OAUTH_CLIENT_SECRET_BROKEN", raising=False)
    monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN_BROKEN", raising=False)
    r = _client(app).get("/api/youtube/profiles")
    assert r.status_code == 200
    assert "BROKEN" not in r.get_json()["profiles"]


def test_profiles_returns_empty_when_no_env(app, monkeypatch):
    monkeypatch.delenv("YOUTUBE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("YOUTUBE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN", raising=False)
    for k in list(__import__("os").environ.keys()):
        if k.startswith("YOUTUBE_OAUTH_CLIENT_ID_"):
            monkeypatch.delenv(k, raising=False)
    r = _client(app).get("/api/youtube/profiles")
    assert r.status_code == 200
    assert r.get_json()["profiles"] == []


def test_channel_info_returns_resolve_label_output(app, monkeypatch):
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "rtok")

    fake = {
        "profile": "(default)",
        "aud": "client.example.com",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    }
    with patch(
        "platform_clients.youtube._resolve_channel_label",
        return_value=fake,
    ):
        r = _client(app).get("/api/youtube/channel-info")
    assert r.status_code == 200
    assert r.get_json() == fake


def test_channel_info_with_profile_overrides_env_temporarily(app, monkeypatch):
    """profile クエリで _resolve_channel_label 中だけ env が override される。"""
    import os

    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "rtok")
    monkeypatch.setenv("YOUTUBE_PROFILE", "ORIGINAL")

    seen: dict[str, str | None] = {}

    def _capture():
        seen["profile_during_call"] = os.environ.get("YOUTUBE_PROFILE")
        return {"profile": os.environ.get("YOUTUBE_PROFILE") or "(default)"}

    with patch(
        "platform_clients.youtube._resolve_channel_label",
        side_effect=_capture,
    ):
        r = _client(app).get("/api/youtube/channel-info?profile=brand")

    assert r.status_code == 200
    assert seen["profile_during_call"] == "BRAND"
    # 呼び出し後は元の値に戻っている
    assert os.environ.get("YOUTUBE_PROFILE") == "ORIGINAL"
