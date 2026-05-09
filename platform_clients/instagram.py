"""Instagram Graph API クライアント (Reels / Insights / Upload)。

Business / Creator アカウント + 連携した Facebook Page + アプリレビュー
通過済みの長期 access token が前提。`upload_video()` は scope
``instagram_content_publish`` を要求する。

環境変数:
    INSTAGRAM_ACCESS_TOKEN  long-lived user access token
    INSTAGRAM_BUSINESS_ID   IG Business Account ID (= /me/accounts から取得)
"""
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"
CONTAINER_POLL_INTERVAL_SEC = 5
CONTAINER_POLL_MAX_SEC = 600


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


def upload_video(
    file_path: Path | str,
    caption: str,
    *,
    media_type: str = "REELS",
) -> dict:
    """Reels を Graph API で公開する (= mode=api 経路)。

    1. ``platform_clients.temp_hosting`` で動画を S3/R2 に一時 upload して
       公開 https URL を作る (= IG は file body を受け取らず URL から PULL する)
    2. ``POST /{ig-user-id}/media`` で container 作成
    3. ``GET /{container-id}`` で ``status_code=FINISHED`` を polling
    4. ``POST /{ig-user-id}/media_publish?creation_id=...`` で公開
    5. 一時 URL は finally で削除

    Returns:
        ``{"video_id": <ig_media_id>, "url": <permalink>, "raw_response": {...}}``

    Raises:
        RuntimeError: 認証情報不足 / temp_hosting 設定不足 / 異常レスポンス
    """
    import requests
    from . import temp_hosting

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(str(file_path))

    token, biz = _credentials()
    host = temp_hosting.get_temp_host()
    key, video_url = host.upload(file_path)

    try:
        # 1) container 作成
        resp = requests.post(
            f"{GRAPH_API_BASE}/{biz}/media",
            data={
                "media_type": media_type,
                "video_url": video_url,
                "caption": caption[:2200],  # IG 上限 ~2200 文字
                "access_token": token,
            },
            timeout=60,
        )
        resp.raise_for_status()
        container_id = (resp.json() or {}).get("id")
        if not container_id:
            raise RuntimeError(
                f"IG container id 取得失敗: {resp.text[:300]}",
            )

        # 2) container status を polling
        deadline = time.monotonic() + CONTAINER_POLL_MAX_SEC
        while time.monotonic() < deadline:
            sresp = requests.get(
                f"{GRAPH_API_BASE}/{container_id}",
                params={
                    "fields": "status_code,status",
                    "access_token": token,
                },
                timeout=20,
            )
            sresp.raise_for_status()
            sdata = sresp.json() or {}
            status_code = sdata.get("status_code")
            if status_code == "FINISHED":
                break
            if status_code == "ERROR":
                raise RuntimeError(
                    f"IG container failed: {sdata.get('status') or sdata}",
                )
            time.sleep(CONTAINER_POLL_INTERVAL_SEC)
        else:
            raise RuntimeError(
                f"IG container timeout after {CONTAINER_POLL_MAX_SEC}s",
            )

        # 3) media_publish
        presp = requests.post(
            f"{GRAPH_API_BASE}/{biz}/media_publish",
            data={
                "creation_id": container_id,
                "access_token": token,
            },
            timeout=60,
        )
        presp.raise_for_status()
        pdata = presp.json() or {}
        media_id = pdata.get("id")
        if not media_id:
            raise RuntimeError(
                f"IG publish 後に media_id 取得失敗: {presp.text[:300]}",
            )

        # 4) permalink 取得 (= 任意。失敗しても publish 自体は成功)
        permalink: str | None = None
        try:
            lresp = requests.get(
                f"{GRAPH_API_BASE}/{media_id}",
                params={"fields": "permalink", "access_token": token},
                timeout=20,
            )
            if lresp.ok:
                permalink = (lresp.json() or {}).get("permalink")
        except Exception as e:
            logger.warning("[ig] permalink 取得失敗 (= 続行): %s", e)

        return {
            "video_id": media_id,
            "url": permalink or f"https://www.instagram.com/reel/{media_id}/",
            "raw_response": pdata,
        }
    finally:
        host.delete(key)
