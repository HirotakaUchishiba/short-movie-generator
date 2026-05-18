#!/usr/bin/env python3
"""OAuth 認証された YouTube チャンネルの ID と概要を表示する。

`YOUTUBE_REFRESH_TOKEN` が指す Google アカウントで `channels?mine=true` を叩く。
upload 先 / Analytics 対象が意図したチャンネルか確認するための診断用。

使い方:
    python3 scripts/check_youtube_channel.py
"""
import logging
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
from platform_clients.youtube import _oauth_access_token  # noqa: E402

log_setup.setup()
logger = logging.getLogger(__name__)


def main() -> int:
    import requests
    from dotenv import load_dotenv

    load_dotenv()

    cid = os.environ.get("YOUTUBE_OAUTH_CLIENT_ID")
    csec = os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET")
    rtok = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not all([cid, csec, rtok]):
        logger.error(
            "YOUTUBE_OAUTH_CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN を .env に設定してください",
        )
        return 1

    token = _oauth_access_token(cid, csec, rtok)

    info_resp = requests.get(
        "https://oauth2.googleapis.com/tokeninfo",
        params={"access_token": token},
        timeout=20,
    )
    info_resp.raise_for_status()
    info = info_resp.json()
    scopes = (info.get("scope") or "").split()
    logger.info("google_email: %s", info.get('email'))
    logger.info("google_sub  : %s", info.get('sub'))
    logger.info("audience    : %s", info.get('aud'))
    logger.info("scopes      : %s", scopes)

    has_youtube_read = any(
        s in scopes
        for s in (
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/youtube",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        )
    )
    if not has_youtube_read:
        logger.warning(
            "⚠ チャンネル詳細 (= title / subscribers / channel_id) を取得するには "
            "scope `https://www.googleapis.com/auth/youtube.readonly` が不足しています。",
        )
        logger.warning(
            "  対処: OAuth Playground で再 Authorize 時にこの scope も追加して "
            "新しい refresh_token を発行 → .env に上書き。",
        )
        logger.warning(
            "  なお現状の scope (`youtube.upload` + `yt-analytics.readonly`) で "
            "upload と Analytics 取得自体は動作します。",
        )
        return 0

    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet,statistics", "mine": "true"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        logger.error(
            "OAuth ユーザーにチャンネルが紐付いていません "
            "(= YouTube チャンネル未作成 / ブランドアカウントが選ばれていない可能性)",
        )
        return 1

    for ch in items:
        s = ch.get("snippet", {})
        st = ch.get("statistics", {})
        logger.info("channel_id  : %s", ch.get('id'))
        logger.info("title       : %s", s.get('title'))
        logger.info("custom_url  : %s", s.get('customUrl'))
        logger.info("published_at: %s", s.get('publishedAt'))
        logger.info("subscribers : %s", st.get('subscriberCount'))
        logger.info("videos      : %s", st.get('videoCount'))
        logger.info("views       : %s", st.get('viewCount'))
        logger.info("url         : https://www.youtube.com/channel/%s", ch.get('id'))
    return 0


if __name__ == "__main__":
    sys.exit(main())
