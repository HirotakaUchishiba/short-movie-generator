"""Instagram Graph API クライアント (Reels / Insights)。

Phase 1 のスケルトン。Business / Creator アカウント + 連携した Facebook Page
+ アプリレビュー通過済みの長期 access token が前提。

環境変数:
    INSTAGRAM_ACCESS_TOKEN  long-lived user access token
    INSTAGRAM_BUSINESS_ID   IG Business Account ID (= /me/accounts から取得)
"""
import logging
import os

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


def _credentials() -> tuple[str, str]:
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    biz = os.getenv("INSTAGRAM_BUSINESS_ID")
    if not token or not biz:
        raise RuntimeError(
            "INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID 未設定",
        )
    return token, biz


def fetch_insights(media_id: str) -> dict:
    """Reels の insights を取得する。Phase 1 仮実装。

    metrics:
      - reach (= 閲覧した一意ユーザー)
      - plays (= 再生回数)
      - likes / comments / saved / shares
      - total_interactions
    """
    import requests

    token, _ = _credentials()
    fields = ",".join([
        "reach", "plays", "likes", "comments", "saved", "shares",
        "total_interactions",
    ])
    resp = requests.get(
        f"{GRAPH_API_BASE}/{media_id}/insights",
        params={"metric": fields, "access_token": token},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    out: dict = {"raw_response": data}
    for entry in data.get("data") or []:
        name = entry.get("name")
        values = entry.get("values") or []
        if not name or not values:
            continue
        out[name] = values[0].get("value")
    out["views"] = out.get("plays")
    out["saves"] = out.get("saved")
    return out


def fetch_metrics_for_post(post: dict) -> dict:
    """analytics DB の post 1 行を受け取り、最新メトリクスを返す。

    `post["platform_post_id"]` は IG Graph API 形式の media_id (= 数字列)。
    """
    return fetch_insights(post["platform_post_id"])
