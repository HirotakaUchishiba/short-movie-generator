#!/usr/bin/env python3
"""登録済み全postの最新metricsをプラットフォームAPIから取得してDBに追記する。

使い方:
    python3 scripts/fetch_metrics.py                 # 全post
    python3 scripts/fetch_metrics.py --platform youtube
    python3 scripts/fetch_metrics.py --post-id youtube:abc123
"""
import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
from analytics import db  # noqa: E402
from platform_clients import instagram, tiktok, youtube  # noqa: E402

log_setup.setup()
logger = logging.getLogger(__name__)

PLATFORM_CLIENTS = {
    "youtube": youtube.fetch_metrics_for_post,
    "instagram": instagram.fetch_metrics_for_post,
    "tiktok": tiktok.fetch_metrics_for_post,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="全投稿のmetricsを取得してDBに追記")
    parser.add_argument("--platform", choices=list(PLATFORM_CLIENTS.keys()),
                        help="特定プラットフォームのみ")
    parser.add_argument("--post-id", help="特定post-idのみ")
    args = parser.parse_args()

    db.init_db()
    posts = db.list_active_posts(platform=args.platform)
    if args.post_id:
        posts = [p for p in posts if p["id"] == args.post_id]

    if not posts:
        logger.warning("対象postが見つかりません")
        return 0

    success = 0
    failed = 0
    for post in posts:
        platform = post["platform"]
        fetcher = PLATFORM_CLIENTS.get(platform)
        if not fetcher:
            logger.info("%s: %s 未対応プラットフォーム", post["id"], platform)
            continue
        try:
            metrics = fetcher(post)
            db.insert_metrics(post["id"], metrics)
            success += 1
            logger.info("%s views=%s likes=%s comments=%s",
                        post["id"], metrics.get("views"),
                        metrics.get("likes"), metrics.get("comments"))
        except Exception as e:
            failed += 1
            logger.error("%s 取得失敗: %s", post["id"], e)

    logger.info("完了: %d成功 / %d失敗", success, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
