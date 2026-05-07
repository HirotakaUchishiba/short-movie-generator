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
from analytics import pending_queue  # noqa: E402
from final_import.publish import finalize_pending_publish  # noqa: E402

log_setup.setup()
logger = logging.getLogger(__name__)


def sync() -> tuple[int, int]:
    """queue を replay し、成功した ts については Stage 8 を mark_generated。"""
    result = pending_queue.replay()
    if result["success"] == 0 and result["failed"] == 0:
        logger.info("queue は空です")
        return 0, 0

    for ts in set(result["synced_ts"]):
        try:
            finalize_pending_publish(ts)
        except Exception as e:
            logger.warning("finalize_pending_publish(%s) 失敗: %s", ts, e)

    logger.info(
        "完了: %d成功 / %d失敗 (残 queue %d)",
        result["success"], result["failed"],
        result["failed"],
    )
    return result["success"], result["failed"]


def main() -> int:
    _, failed = sync()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
