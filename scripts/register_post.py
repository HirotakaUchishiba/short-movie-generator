#!/usr/bin/env python3
"""投稿URLをAnalytics DBに登録する。

使い方:
    python3 scripts/register_post.py <video_id> youtube <URL_or_video_id>
    python3 scripts/register_post.py 20260425_123456 youtube https://youtube.com/watch?v=abc
    python3 scripts/register_post.py 20260425_123456 youtube abc123 --posted-at 2026-04-25T10:00:00
"""
import argparse
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
from analytics import db  # noqa: E402

log_setup.setup()
logger = logging.getLogger(__name__)


def _extract_youtube_id(url_or_id: str) -> str:
    if "youtube.com" not in url_or_id and "youtu.be" not in url_or_id:
        return url_or_id
    parsed = urlparse(url_or_id)
    if parsed.netloc.endswith("youtu.be"):
        return parsed.path.lstrip("/")
    qs = parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0]
    m = re.search(r"/shorts/([A-Za-z0-9_-]+)", parsed.path)
    if m:
        return m.group(1)
    raise ValueError(f"YouTube ID抽出不能: {url_or_id}")


def _extract_post_id(platform: str, url_or_id: str) -> str:
    if platform == "youtube":
        return _extract_youtube_id(url_or_id)
    return url_or_id


def main() -> int:
    parser = argparse.ArgumentParser(description="投稿URLをDBに登録")
    parser.add_argument("video_id", help="生成動画のID (timestamp)")
    parser.add_argument("platform", choices=["youtube", "tiktok", "instagram"])
    parser.add_argument("url_or_id", help="投稿URL または プラットフォーム側のID")
    parser.add_argument("--posted-at", help="投稿日時 ISO8601")
    parser.add_argument("--caption", help="投稿キャプション")
    parser.add_argument("--hashtags", help="ハッシュタグ（カンマ区切り）")
    args = parser.parse_args()

    db.init_db()

    post_id = _extract_post_id(args.platform, args.url_or_id)
    url = args.url_or_id if args.url_or_id.startswith("http") else None
    hashtags = [h.strip() for h in args.hashtags.split(",")] if args.hashtags else None

    resolved_post_id = db.register_post(
        video_id=args.video_id,
        platform=args.platform,
        platform_post_id=post_id,
        url=url,
        posted_at=args.posted_at,
        caption=args.caption,
        hashtags=hashtags,
    )
    logger.info("登録完了: %s", resolved_post_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
