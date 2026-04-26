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
