#!/usr/bin/env python3
"""TikTok Studio Web の Video performance CSV を analytics DB に取り込む。

API 審査が通るまでの繋ぎ。CSV を毎日 (or 毎週) ダウンロードしてこのスクリプトに食わせる。

使い方:
    python3 scripts/ingest_tiktok_csv.py path/to/video_performance.csv
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
from platform_clients.tiktok import parse_studio_csv  # noqa: E402

log_setup.setup()
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="TikTok Studio CSV → analytics DB")
    parser.add_argument("csv_path", help="TikTok Studio エクスポート CSV")
    args = parser.parse_args()

    db.init_db()
    csv_text = Path(args.csv_path).read_text(encoding="utf-8")
    rows = parse_studio_csv(csv_text)

    posts = {p["platform_post_id"]: p for p in db.list_active_posts(platform="tiktok")}
    success = 0
    skipped = 0
    for r in rows:
        pid = r["platform_post_id"]
        if not pid:
            continue
        if pid not in posts:
            logger.info("未登録の TikTok post をスキップ: %s (register_post で先に登録)", pid)
            skipped += 1
            continue
        post = posts[pid]
        db.insert_metrics(post["id"], r)
        logger.info("metrics 取込: %s views=%s", pid, r.get("views"))
        success += 1
    logger.info("完了: %d 取込 / %d スキップ", success, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
