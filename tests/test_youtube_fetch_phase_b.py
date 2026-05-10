"""Phase B: youtube.fetch_analytics 拡張 / fetch_traffic_sources /
fetch_retention_curve の mock unit test."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from platform_clients import youtube


@pytest.fixture
def oauth_env(monkeypatch):
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "ref")


# ───────────── fetch_analytics 拡張 ─────────────

def test_fetch_analytics_returns_v10_kpis(oauth_env):
    """core metrics + impressions/CTR 別 request の統合 return shape を確認。"""
    core_resp = MagicMock()
    core_resp.json.return_value = {
        "columnHeaders": [
            {"name": "views"}, {"name": "likes"}, {"name": "comments"},
            {"name": "shares"}, {"name": "averageViewDuration"},
            {"name": "averageViewPercentage"},
            {"name": "estimatedMinutesWatched"},
            {"name": "subscribersGained"},
        ],
        "rows": [[1000, 50, 5, 2, 22.5, 60.0, 250.0, 12]],
    }
    core_resp.raise_for_status = MagicMock()

    imp_resp = MagicMock()
    imp_resp.json.return_value = {
        "columnHeaders": [
            {"name": "impressions"},
            {"name": "impressionsClickThroughRate"},
        ],
        "rows": [[25000, 4.0]],
    }
    imp_resp.raise_for_status = MagicMock()

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", side_effect=[core_resp, imp_resp]):
        result = youtube.fetch_analytics("abc")

    assert result["views"] == 1000
    assert result["completion_rate"] == pytest.approx(0.6)
    assert result["impressions"] == 25000
    assert result["ctr"] == pytest.approx(0.04)  # 4.0% → 0.04
    assert result["subscribers_gained"] == 12


def test_fetch_analytics_impressions_query_failure_keeps_core(oauth_env):
    """impressions/CTR の別 request が 4xx でも core metrics は壊さない。"""
    core_resp = MagicMock()
    core_resp.json.return_value = {
        "columnHeaders": [
            {"name": "views"}, {"name": "averageViewPercentage"},
        ],
        "rows": [[100, 50.0]],
    }
    core_resp.raise_for_status = MagicMock()

    imp_resp = MagicMock()
    imp_resp.raise_for_status.side_effect = RuntimeError("impressions 400")

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", side_effect=[core_resp, imp_resp]):
        result = youtube.fetch_analytics("abc")

    assert result["views"] == 100
    assert result["impressions"] is None
    assert result["ctr"] is None


def test_fetch_analytics_missing_impressions_rows_returns_none(oauth_env):
    """impressions query が空 rows でも core 値は壊れず impressions=None。"""
    core_resp = MagicMock()
    core_resp.json.return_value = {
        "columnHeaders": [
            {"name": "views"}, {"name": "averageViewPercentage"},
        ],
        "rows": [[100, 50.0]],
    }
    core_resp.raise_for_status = MagicMock()

    imp_resp = MagicMock()
    imp_resp.json.return_value = {"rows": []}
    imp_resp.raise_for_status = MagicMock()

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", side_effect=[core_resp, imp_resp]):
        result = youtube.fetch_analytics("abc")

    assert result["views"] == 100
    assert result["impressions"] is None
    assert result["ctr"] is None


def test_fetch_analytics_empty_rows_returns_only_raw(oauth_env):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"rows": []}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", return_value=mock_resp):
        result = youtube.fetch_analytics("abc")
    assert "raw_response" in result
    assert "views" not in result


# ───────────── fetch_traffic_sources ─────────────

def test_fetch_traffic_sources_computes_share(oauth_env):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "columnHeaders": [
            {"name": "insightTrafficSourceType"}, {"name": "views"},
        ],
        "rows": [
            ["YT_BROWSE", 600],
            ["RELATED_VIDEO", 250],
            ["YT_SEARCH", 100],
            ["EXT_URL", 50],
            ["NOTIFICATION", 25],  # _TRAFFIC_TYPE_TO_KEY に無い → other 扱い
        ],
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", return_value=mock_resp):
        result = youtube.fetch_traffic_sources("abc")

    total = 600 + 250 + 100 + 50 + 25
    assert result["traffic_browse_pct"] == pytest.approx(600 / total)
    assert result["traffic_suggested_pct"] == pytest.approx(250 / total)
    assert result["traffic_search_pct"] == pytest.approx(100 / total)
    assert result["traffic_external_pct"] == pytest.approx(50 / total)
    # 合計が 1.0 を下回る (= other に 25 行ったため)
    assert sum(result[k] for k in (
        "traffic_browse_pct", "traffic_suggested_pct",
        "traffic_search_pct", "traffic_external_pct",
    )) < 1.0


def test_fetch_traffic_sources_empty_returns_only_raw(oauth_env):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"rows": []}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", return_value=mock_resp):
        result = youtube.fetch_traffic_sources("abc")
    assert "traffic_browse_pct" not in result


# ───────────── fetch_retention_curve ─────────────

def test_fetch_retention_curve_parses_curve(oauth_env):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "columnHeaders": [
            {"name": "elapsedVideoTimeRatio"},
            {"name": "audienceWatchRatio"},
            {"name": "relativeRetentionPerformance"},
        ],
        "rows": [
            [0.0, 1.0, 1.0],
            [0.25, 0.85, 1.05],
            [0.5, 0.6, 0.95],
            [0.75, 0.4, 0.9],
            [1.0, 0.2, 0.8],
        ],
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", return_value=mock_resp):
        result = youtube.fetch_retention_curve("abc", duration_sec=60.0)

    assert len(result["curve"]) == 5
    first = result["curve"][0]
    assert first["elapsed_pct"] == pytest.approx(0.0)
    assert first["ratio"] == pytest.approx(1.0)
    assert first["elapsed_sec"] == pytest.approx(0.0)
    middle = result["curve"][2]
    assert middle["elapsed_sec"] == pytest.approx(30.0)


def test_fetch_retention_curve_no_duration_omits_seconds(oauth_env):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "columnHeaders": [
            {"name": "elapsedVideoTimeRatio"},
            {"name": "audienceWatchRatio"},
            {"name": "relativeRetentionPerformance"},
        ],
        "rows": [[0.5, 0.6, 0.9]],
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", return_value=mock_resp):
        result = youtube.fetch_retention_curve("abc")

    assert result["curve"][0].get("elapsed_sec") is None


def test_fetch_retention_curve_empty_rows_returns_empty_curve(oauth_env):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"rows": []}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", return_value=mock_resp):
        result = youtube.fetch_retention_curve("abc")
    assert result["curve"] == []


def test_fetch_retention_curve_sorts_by_elapsed_pct(oauth_env):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "columnHeaders": [
            {"name": "elapsedVideoTimeRatio"},
            {"name": "audienceWatchRatio"},
            {"name": "relativeRetentionPerformance"},
        ],
        "rows": [
            [0.5, 0.6, 0.95],
            [0.0, 1.0, 1.0],
            [0.25, 0.85, 1.05],
        ],
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", return_value=mock_resp):
        result = youtube.fetch_retention_curve("abc")
    pcts = [p["elapsed_pct"] for p in result["curve"]]
    assert pcts == sorted(pcts)


# ───────────── fetch_metrics_for_post 統合 ─────────────

def test_fetch_metrics_for_post_routes_retention_curve_separately(oauth_env, monkeypatch):
    """fetch_metrics_for_post が retention curve を _retention_curve キーで返す."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")

    def _mock_get(url, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        params = kwargs.get("params") or {}
        dims = params.get("dimensions") or ""
        metrics_q = params.get("metrics") or ""
        if "elapsedVideoTimeRatio" in dims:
            m.json.return_value = {
                "columnHeaders": [
                    {"name": "elapsedVideoTimeRatio"},
                    {"name": "audienceWatchRatio"},
                    {"name": "relativeRetentionPerformance"},
                ],
                "rows": [[0.5, 0.6, 1.0]],
            }
        elif "insightTrafficSourceType" in dims:
            m.json.return_value = {
                "columnHeaders": [
                    {"name": "insightTrafficSourceType"},
                    {"name": "views"},
                ],
                "rows": [["YT_BROWSE", 100]],
            }
        elif "impressions" in metrics_q and "views" not in metrics_q:
            # _fetch_impressions_metrics 専用 query (= core metrics と分離済)
            m.json.return_value = {
                "columnHeaders": [
                    {"name": "impressions"},
                    {"name": "impressionsClickThroughRate"},
                ],
                "rows": [[5000, 3.5]],
            }
        elif "youtubeanalytics" in url:
            # core fetch_analytics (= subscribers_gained 等)
            m.json.return_value = {
                "columnHeaders": [
                    {"name": "views"},
                    {"name": "averageViewPercentage"},
                    {"name": "subscribersGained"},
                ],
                "rows": [[100, 60.0, 3]],
            }
        else:
            # Data API public stats
            m.json.return_value = {
                "items": [{
                    "statistics": {
                        "viewCount": "100", "likeCount": "1", "commentCount": "0",
                    },
                    "contentDetails": {"duration": "PT60S"},
                    "snippet": {"title": "t"},
                }],
            }
        return m

    with patch.object(youtube, "_oauth_access_token", return_value="tok"), \
         patch("requests.get", side_effect=_mock_get):
        result = youtube.fetch_metrics_for_post({
            "platform_post_id": "abc",
        })

    assert "_retention_curve" in result
    assert result["_retention_curve"][0]["elapsed_pct"] == pytest.approx(0.5)
    assert result["traffic_browse_pct"] == pytest.approx(1.0)
    assert result["views"] == 100
