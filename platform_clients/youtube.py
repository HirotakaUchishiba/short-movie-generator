"""YouTube Data API v3 / Analytics API クライアント + resumable uploader。

環境変数:
    YOUTUBE_API_KEY                  公開統計(views/likes/comments/duration)用
    YOUTUBE_OAUTH_CLIENT_ID          Analytics / Upload API 用 (OAuth Desktop App)
    YOUTUBE_OAUTH_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN            初回認可後に取得、.env保存推奨
                                     (upload を使うなら youtube.upload scope 同意必須)
"""
import logging
import os
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API_BASE = "https://youtubeanalytics.googleapis.com/v2"
UPLOAD_API_BASE = "https://www.googleapis.com/upload/youtube/v3/videos"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
DEFAULT_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_CATEGORY_ID = "22"  # People & Blogs


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


def upload_video(
    file_path: Path | str,
    title: str,
    description: str,
    tags: list[str] | None = None,
    privacy: str = "private",
    is_short: bool = True,
    category_id: str = DEFAULT_CATEGORY_ID,
    chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
    made_for_kids: bool = False,
) -> dict:
    """Resumable upload で YouTube に動画をアップロード、video_id と URL を返す。

    privacy: "private" / "unlisted" / "public"。既定は "private" で安全側。
    is_short: True なら description 末尾に `#Shorts` を自動付加し、Shorts URL を返す。

    Raises:
        RuntimeError: 認証情報不足 / Location ヘッダ欠落 / 異常レスポンス
        requests.HTTPError: HTTP エラー (403 はスコープ不足の可能性)
    """
    import requests

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"video not found: {file_path}")
    file_size = file_path.stat().st_size
    if file_size <= 0:
        raise ValueError(f"empty file: {file_path}")

    client_id = os.getenv("YOUTUBE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET")
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "YOUTUBE_OAUTH_CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN が必要 "
            "(upload には youtube.upload スコープ同意済みの token が必要)",
        )

    token = _oauth_access_token(client_id, client_secret, refresh_token)

    if is_short and "#Shorts" not in description:
        description = (description.rstrip() + "\n\n#Shorts").strip()

    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:30],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    init_resp = requests.post(
        f"{UPLOAD_API_BASE}?uploadType=resumable&part=snippet,status",
        json=metadata,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Upload-Content-Length": str(file_size),
            "X-Upload-Content-Type": "video/*",
        },
        timeout=30,
    )
    init_resp.raise_for_status()
    upload_url = init_resp.headers.get("Location")
    if not upload_url:
        raise RuntimeError("resumable upload init で Location header が返らなかった")

    with open(file_path, "rb") as f:
        offset = 0
        last_response_data: dict = {}
        while offset < file_size:
            f.seek(offset)
            chunk = f.read(chunk_size)
            if not chunk:
                break
            chunk_end = offset + len(chunk) - 1
            r = requests.put(
                upload_url,
                data=chunk,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{chunk_end}/{file_size}",
                },
                timeout=600,
            )
            if r.status_code in (200, 201):
                try:
                    last_response_data = r.json()
                except Exception:
                    last_response_data = {}
                break
            if r.status_code == 308:
                range_header = r.headers.get("Range") or r.headers.get("range")
                if range_header and "-" in range_header:
                    end = int(range_header.rsplit("-", 1)[-1])
                    offset = end + 1
                else:
                    offset += len(chunk)
                logger.info(
                    "youtube upload: %d / %d bytes (%.0f%%)",
                    offset, file_size, offset / file_size * 100,
                )
                continue
            r.raise_for_status()
            raise RuntimeError(
                f"upload PUT 想定外の status: {r.status_code} {r.text[:300]}",
            )

    video_id = last_response_data.get("id")
    if not video_id:
        raise RuntimeError(
            f"upload 完了後に video_id が取得できませんでした: {last_response_data}",
        )
    url = (f"https://youtube.com/shorts/{video_id}" if is_short
           else f"https://youtu.be/{video_id}")
    return {
        "video_id": video_id,
        "url": url,
        "raw_response": last_response_data,
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
