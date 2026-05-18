#!/usr/bin/env python3
"""analytics DB を最新スキーマに migrate する。

`analytics.db.init_db()` を呼ぶだけの薄いシン。
schema.sql の `CREATE TABLE IF NOT EXISTS` と
`db._ensure_column` を組み合わせた additive migration なので、既存 DB を
壊さずに新カラム / 新テーブルを追加する。

CI / 本番 cron 起動前に毎回実行しても idempotent。

使い方:
    python3 scripts/migrate.py
"""
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
from analytics import db  # noqa: E402


def main() -> int:
    log_setup.setup()
    logger = logging.getLogger(__name__)
    db.init_db()
    logger.info("analytics DB migration: schema v%s applied",
                db.CURRENT_SCHEMA_VERSION)
    return 0


if __name__ == "__main__":
    sys.exit(main())
