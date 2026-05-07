#!/usr/bin/env python3
"""analytics_pending.jsonl の queue を消費して analytics DB に再登録する。

publish 時に DB 書き込みが失敗した entry が `data/analytics_pending.jsonl`
に積まれる。このスクリプトを実行すると 1 行ずつ DB に再登録し、成功した
行だけ queue から削除する。

使い方:
    python3 scripts/sync_pending_analytics.py
"""
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
from analytics import db, pending_queue  # noqa: E402

log_setup.setup()
logger = logging.getLogger(__name__)


def sync() -> tuple[int, int]:
    entries = pending_queue.read_all()
    if not entries:
        logger.info("queue は空です")
        return 0, 0

    db.init_db()
    remaining: list[dict] = []
    success = 0
    failed = 0
    for entry in entries:
        try:
            db.register_post(
                video_id=entry["ts"],
                platform=entry["platform"],
                platform_post_id=entry["platform_post_id"],
                url=entry.get("url"),
                posted_at=entry.get("posted_at"),
                caption=entry.get("caption"),
                hashtags=entry.get("hashtags"),
            )
            success += 1
            logger.info("同期成功: %s:%s",
                        entry["platform"], entry["platform_post_id"])
        except Exception as e:
            failed += 1
            remaining.append(entry)
            logger.error("同期失敗 (queue に残します): %s:%s — %s",
                         entry.get("platform"),
                         entry.get("platform_post_id"), e)

    pending_queue.rewrite(remaining)
    logger.info("完了: %d成功 / %d失敗 (残 queue %d)",
                success, failed, len(remaining))
    return success, failed


def main() -> int:
    _, failed = sync()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
