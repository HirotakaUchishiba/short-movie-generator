"""YouTube Data API v3 / Analytics API クライアント。

環境変数:
    YOUTUBE_API_KEY                  公開統計(views/likes/comments/duration)用
    YOUTUBE_OAUTH_CLIENT_ID          Analytics API用 (OAuth Desktop App)
    YOUTUBE_OAUTH_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN            初回認可後に取得、.env保存推奨
"""
import logging
import os
from datetime import date, timedelta

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API_BASE = "https://youtubeanalytics.googleapis.com/v2"


def _iso_duration_to_seconds(dur: str) -> float:
    """ISO 8601 duration 'PT1M30S' → 90.0"""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur or "")
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + int(s or 0)


def fetch_public_stats(video_id: str, api_key: str | None = None) -> dict:
    """YouTube Data API v3 で公開統計を取得。"""
    import requests

    key = api_key or os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY未設定")

    resp = requests.get(
        f"{DATA_API_BASE}/videos",
        params={
            "id": video_id,
            "part": "statistics,contentDetails,snippet",
            "key": key,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"YouTube動画が見つかりません: {video_id}")

    item = items[0]
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})
    snippet = item.get("snippet", {})

    return {
        "views": int(stats.get("viewCount", 0) or 0),
        "likes": int(stats.get("likeCount", 0) or 0),
        "comments": int(stats.get("commentCount", 0) or 0),
        "favorites": int(stats.get("favoriteCount", 0) or 0),
        "duration_sec": _iso_duration_to_seconds(content.get("duration", "")),
        "title": snippet.get("title"),
        "published_at": snippet.get("publishedAt"),
        "raw_response": item,
    }


def _oauth_access_token(client_id: str, client_secret: str,
                        refresh_token: str) -> str:
    import requests
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_analytics(video_id: str,
                    start_date: str | None = None,
                    end_date: str | None = None) -> dict:
    """YouTube Analytics API で詳細メトリクスを取得（要OAuth、自チャンネル動画のみ）。"""
    import requests

    client_id = os.getenv("YOUTUBE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET")
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "YouTube Analytics認証情報が未設定 "
            "(YOUTUBE_OAUTH_CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN)"
        )

    token = _oauth_access_token(client_id, client_secret, refresh_token)

    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()
    if not end_date:
        end_date = date.today().isoformat()

    metrics = ",".join([
        "views", "likes", "comments", "shares",
        "averageViewDuration", "averageViewPercentage",
        "estimatedMinutesWatched", "subscribersGained",
    ])

    resp = requests.get(
        f"{ANALYTICS_API_BASE}/reports",
        params={
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": metrics,
            "filters": f"video=={video_id}",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    rows = data.get("rows") or []
    if not rows:
        return {"raw_response": data}

    headers = [h["name"] for h in data.get("columnHeaders", [])]
    values = rows[0]
    m = dict(zip(headers, values))

    watch_sec = float(m.get("estimatedMinutesWatched", 0) or 0) * 60.0
    avg_view_duration = float(m.get("averageViewDuration", 0) or 0)
    avg_view_pct = float(m.get("averageViewPercentage", 0) or 0)

    return {
        "views": int(m.get("views", 0) or 0),
        "likes": int(m.get("likes", 0) or 0),
        "comments": int(m.get("comments", 0) or 0),
        "shares": int(m.get("shares", 0) or 0),
        "watch_time_sec": watch_sec,
        "avg_view_duration": avg_view_duration,
        "completion_rate": avg_view_pct / 100.0 if avg_view_pct else None,
        "raw_response": data,
    }


def fetch_metrics_for_post(post: dict) -> dict:
    """dbから取った1 post dictに対してmetricsを取得。Analytics取れなければData APIで補完。"""
    video_id = post["platform_post_id"]
    result: dict = {}

    try:
        analytics = fetch_analytics(video_id)
        result.update({k: v for k, v in analytics.items() if v is not None})
    except Exception as e:
        logger.info("YouTube Analytics 取得スキップ (%s): %s", video_id, e)

    try:
        public = fetch_public_stats(video_id)
        for k, v in public.items():
            if k not in result or result.get(k) in (None, 0):
                result[k] = v
    except Exception as e:
        logger.warning("YouTube public stats 取得失敗 (%s): %s", video_id, e)

    return result
