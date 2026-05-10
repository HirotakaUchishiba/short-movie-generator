"""Phase B: 実 YouTube Analytics API を叩く smoke test。

env が揃っているときだけ走る。 走らせると自チャンネルの ``YOUTUBE_TEST_VIDEO_ID``
動画について Analytics / Traffic Sources / Retention Curve の 3 経路を 1 回ずつ叩いて、
return shape に必要キーが揃っていることを確認する。 課金 0 の API だが quota は
消費する。

使い方:
    export YOUTUBE_OAUTH_CLIENT_ID=...
    export YOUTUBE_OAUTH_CLIENT_SECRET=...
    export YOUTUBE_REFRESH_TOKEN=...
    export YOUTUBE_TEST_VIDEO_ID=<own_video_id>
    pytest tests/test_youtube_smoke_phase_b.py -v
"""
from __future__ import annotations

import os

import pytest

from platform_clients import youtube

_REQUIRED_ENV = (
    "YOUTUBE_OAUTH_CLIENT_ID",
    "YOUTUBE_OAUTH_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
    "YOUTUBE_TEST_VIDEO_ID",
)


def _env_ready() -> bool:
    return all(bool(os.environ.get(k)) for k in _REQUIRED_ENV)


pytestmark = pytest.mark.skipif(
    not _env_ready(),
    reason=f"YouTube OAuth env または YOUTUBE_TEST_VIDEO_ID 未設定: "
           f"{[k for k in _REQUIRED_ENV if not os.environ.get(k)]}",
)


def test_fetch_analytics_smoke():
    video_id = os.environ["YOUTUBE_TEST_VIDEO_ID"]
    result = youtube.fetch_analytics(video_id)
    # rows が空でも raw_response は必ず返る (= API 接続が通ったこと)
    assert "raw_response" in result
    # rows がある場合は v10 の追加キーが return に含まれる (= None 含む)
    if "views" in result:
        for k in ("subscribers_gained", "impressions", "ctr"):
            assert k in result, f"v10 key {k!r} が return に無い"


def test_fetch_traffic_sources_smoke():
    video_id = os.environ["YOUTUBE_TEST_VIDEO_ID"]
    result = youtube.fetch_traffic_sources(video_id)
    assert "raw_response" in result
    # rows がある場合は traffic_*_pct のいずれか 1 つ以上が含まれる
    expected = {"traffic_browse_pct", "traffic_suggested_pct",
                "traffic_search_pct", "traffic_external_pct"}
    if any(k in result for k in expected):
        for k in expected:
            v = result.get(k)
            if v is not None:
                assert 0.0 <= float(v) <= 1.0


def test_fetch_retention_curve_smoke():
    video_id = os.environ["YOUTUBE_TEST_VIDEO_ID"]
    result = youtube.fetch_retention_curve(video_id, duration_sec=60.0)
    assert "raw_response" in result
    assert "curve" in result
    # 視聴数が閾値未満だと curve は空 (= API 仕様)、それでも request は通る
    for point in result["curve"]:
        assert "elapsed_pct" in point and "ratio" in point
        assert 0.0 <= point["elapsed_pct"] <= 1.0
        # ratio は通常 0.0〜1.0 だが、relative perf なしの audienceWatchRatio は
        # 1.0 を超えることもある (= ループ視聴等)。下限のみチェック。
        assert point["ratio"] >= 0.0


def test_fetch_metrics_for_post_smoke():
    video_id = os.environ["YOUTUBE_TEST_VIDEO_ID"]
    result = youtube.fetch_metrics_for_post({
        "platform_post_id": video_id,
    })
    # 一つでも metric が取れていれば OK (= 接続成功 + 統合経路が動いている)
    has_any = any(k in result for k in (
        "views", "likes", "comments", "impressions", "ctr",
        "_retention_curve", "traffic_browse_pct",
    ))
    assert has_any, f"fetch_metrics_for_post の return が空: {result.keys()}"
