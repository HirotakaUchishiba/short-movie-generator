"""TikTok クライアント (Display API + CSV import フォールバック)。

Phase 1 のスケルトン。TikTok for Developers での審査通過と open.tiktokapis.com
の OAuth flow が前提。審査が長いので、暫定で TikTok Studio Web の CSV
エクスポート (= scripts でローカル DB に流し込む) もサポート。

環境変数:
    TIKTOK_ACCESS_TOKEN   user access token (display.api スコープ + video.list)
    TIKTOK_OPEN_ID        ユーザー固有の open_id
"""
import csv
import logging
import os
from io import StringIO

logger = logging.getLogger(__name__)

API_BASE = "https://open.tiktokapis.com/v2"


def _credentials() -> tuple[str, str]:
    token = os.getenv("TIKTOK_ACCESS_TOKEN")
    open_id = os.getenv("TIKTOK_OPEN_ID")
    if not token or not open_id:
        raise RuntimeError(
            "TIKTOK_ACCESS_TOKEN / TIKTOK_OPEN_ID 未設定 — "
            "API が使えない場合は CSV エクスポートを scripts/ingest_tiktok_csv.py で取込",
        )
    return token, open_id


def fetch_video_stats(video_id: str) -> dict:
    """指定 video_id の最新統計を返す。"""
    import requests

    token, open_id = _credentials()
    fields = ",".join([
        "id", "view_count", "like_count", "comment_count", "share_count",
        "title", "create_time", "duration",
    ])
    resp = requests.post(
        f"{API_BASE}/video/query/?fields={fields}",
        json={"filters": {"video_ids": [video_id]}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    items = data.get("data", {}).get("videos") or []
    if not items:
        raise RuntimeError(f"TikTok 動画が見つかりません: {video_id}")
    item = items[0]
    return {
        "views": int(item.get("view_count") or 0),
        "likes": int(item.get("like_count") or 0),
        "comments": int(item.get("comment_count") or 0),
        "shares": int(item.get("share_count") or 0),
        "duration_sec": float(item.get("duration") or 0),
        "raw_response": item,
    }


def fetch_metrics_for_post(post: dict) -> dict:
    return fetch_video_stats(post["platform_post_id"])


# ───────── CSV import (TikTok Studio Web のエクスポートを取り込む) ─────────

CSV_FIELD_MAP = {
    "Views": "views",
    "Likes": "likes",
    "Comments": "comments",
    "Shares": "shares",
    "Saved": "saves",
    "Total play time": "watch_time_sec",
    "Average watch time": "avg_view_duration",
    "Watched full video": "completion_rate",
}


def parse_studio_csv(csv_text: str) -> list[dict]:
    """TikTok Studio Web の "Video performance" エクスポート CSV を dict のリストに。

    各 dict には `platform_post_id` (= URL から抽出した数字) と数値フィールドが入る。
    """
    rows = []
    reader = csv.DictReader(StringIO(csv_text))
    for r in reader:
        link = r.get("Video link") or r.get("link") or ""
        post_id = link.rstrip("/").rsplit("/", 1)[-1] if link else ""
        out = {"platform_post_id": post_id, "url": link}
        for src, dst in CSV_FIELD_MAP.items():
            v = r.get(src)
            if v is None or v == "":
                continue
            try:
                if dst == "completion_rate":
                    out[dst] = float(str(v).rstrip("%")) / 100.0
                else:
                    out[dst] = float(str(v).replace(",", ""))
            except ValueError:
                continue
        rows.append(out)
    return rows
