from unittest.mock import MagicMock, patch

import pytest

from platform_clients import youtube


def test_iso_duration_mixed() -> None:
    assert youtube._iso_duration_to_seconds("PT1M30S") == 90
    assert youtube._iso_duration_to_seconds("PT2H5M10S") == 7510
    assert youtube._iso_duration_to_seconds("PT15S") == 15
    assert youtube._iso_duration_to_seconds("") == 0


def test_fetch_public_stats_parses(monkeypatch) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "items": [{
            "statistics": {"viewCount": "12345", "likeCount": "678", "commentCount": "9"},
            "contentDetails": {"duration": "PT55S"},
            "snippet": {"title": "タイトル", "publishedAt": "2026-04-01T00:00:00Z"},
        }]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp):
        stats = youtube.fetch_public_stats("abc", api_key="fake")

    assert stats["views"] == 12345
    assert stats["likes"] == 678
    assert stats["comments"] == 9
    assert stats["duration_sec"] == 55
    assert stats["title"] == "タイトル"


def test_fetch_public_stats_raises_when_empty(monkeypatch) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"items": []}
    mock_resp.raise_for_status = MagicMock()
    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="見つかりません"):
            youtube.fetch_public_stats("nope", api_key="fake")


def test_fetch_public_stats_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="YOUTUBE_API_KEY"):
        youtube.fetch_public_stats("x", api_key=None)


def test_fetch_metrics_for_post_falls_back_to_public(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_OAUTH_CLIENT_ID", raising=False)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "items": [{
            "statistics": {"viewCount": "100", "likeCount": "5", "commentCount": "0"},
            "contentDetails": {"duration": "PT30S"},
            "snippet": {"title": "t"},
        }]
    }
    mock_resp.raise_for_status = MagicMock()
    monkeypatch.setenv("YOUTUBE_API_KEY", "fake")
    with patch("requests.get", return_value=mock_resp):
        m = youtube.fetch_metrics_for_post({"platform_post_id": "abc"})
    assert m["views"] == 100


def test_resolve_oauth_env_no_profile_reads_default(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_PROFILE", raising=False)
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "rtok")
    assert youtube._resolve_oauth_env() == ("cid", "csec", "rtok")


def test_resolve_oauth_env_with_profile_uses_suffix(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_PROFILE", "brand")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "default-cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID_BRAND", "brand-cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET_BRAND", "brand-sec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN_BRAND", "brand-rtok")
    cid, csec, rtok = youtube._resolve_oauth_env()
    assert (cid, csec, rtok) == ("brand-cid", "brand-sec", "brand-rtok")


def test_resolve_oauth_env_profile_falls_back_when_suffix_missing(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_PROFILE", "brand")
    monkeypatch.delenv("YOUTUBE_OAUTH_CLIENT_ID_BRAND", raising=False)
    monkeypatch.delenv("YOUTUBE_OAUTH_CLIENT_SECRET_BRAND", raising=False)
    monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN_BRAND", raising=False)
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "default-cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "default-sec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "default-rtok")
    assert youtube._resolve_oauth_env() == ("default-cid", "default-sec", "default-rtok")


def test_resolve_oauth_env_profile_lowercase_normalized(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_PROFILE", "Brand")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID_BRAND", "brand-cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET_BRAND", "brand-sec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN_BRAND", "brand-rtok")
    cid, _csec, _rtok = youtube._resolve_oauth_env()
    assert cid == "brand-cid"


def test_resolve_channel_label_with_readonly_returns_full_info(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_PROFILE", raising=False)
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "rtok")
    monkeypatch.setattr(youtube, "_oauth_access_token", lambda *a, **k: "tok")

    def _fake_get(url, **_kw):
        resp = MagicMock()
        resp.ok = True
        if "tokeninfo" in url:
            resp.json.return_value = {
                "aud": "client.example.com",
                "scope": (
                    "https://www.googleapis.com/auth/youtube.upload "
                    "https://www.googleapis.com/auth/youtube.readonly"
                ),
            }
        else:
            resp.json.return_value = {
                "items": [{"id": "UCabc", "snippet": {"title": "Test Channel"}}],
            }
        return resp

    with patch("requests.get", side_effect=_fake_get):
        info = youtube._resolve_channel_label()

    assert info["profile"] == "(default)"
    assert info["aud"] == "client.example.com"
    assert info["title"] == "Test Channel"
    assert info["channel_id"] == "UCabc"


def test_resolve_channel_label_without_readonly_omits_channel(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_PROFILE", "BRAND")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID_BRAND", "cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET_BRAND", "csec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN_BRAND", "rtok")
    monkeypatch.setattr(youtube, "_oauth_access_token", lambda *a, **k: "tok")

    def _fake_get(url, **_kw):
        resp = MagicMock()
        resp.ok = True
        if "tokeninfo" in url:
            resp.json.return_value = {
                "aud": "x.example.com",
                "scope": "https://www.googleapis.com/auth/youtube.upload",
            }
            return resp
        raise AssertionError(
            "channels?mine=true should not be called without youtube.readonly",
        )

    with patch("requests.get", side_effect=_fake_get):
        info = youtube._resolve_channel_label()

    assert info["profile"] == "BRAND"
    assert info["aud"] == "x.example.com"
    assert "title" not in info
    assert "channel_id" not in info


def test_resolve_channel_label_missing_oauth_env_returns_error(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_PROFILE", raising=False)
    monkeypatch.delenv("YOUTUBE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("YOUTUBE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN", raising=False)
    info = youtube._resolve_channel_label()
    assert "error" in info
    assert "OAuth env" in info["error"]
