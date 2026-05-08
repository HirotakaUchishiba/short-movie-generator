#!/usr/bin/env python3
"""台本JSONをAnalytics DBに登録し、Claude Haikuで自動タグ付けする。

使い方:
    python3 scripts/ingest_screenplay.py screenplays/19_xxx.json
    python3 scripts/ingest_screenplay.py screenplays/*.json --skip-tags
"""
import argparse
import json
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
from analytics import db, auto_tag  # noqa: E402
from improvement import observed as _observed  # noqa: E402

log_setup.setup()
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="台本JSONをDBに登録しタグ付け")
    parser.add_argument("paths", nargs="+", help="screenplay JSONファイル")
    parser.add_argument("--skip-tags", action="store_true",
                        help="Claude Haikuによる自動タグ付けをスキップ")
    args = parser.parse_args()

    db.init_db()

    for path in args.paths:
        sp_id = db.upsert_screenplay(path)
        if args.skip_tags:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                sp = json.load(f)
            tags = auto_tag.classify_screenplay(sp)
            db.update_screenplay_tags(sp_id, tags)
            logger.info("%s → tags: hook=%s tone=%s emotion=%s theme=%s",
                        sp_id, tags.get("hook_type"), tags.get("tone"),
                        tags.get("dominant_emotion"), tags.get("theme"))
            # auto_tag で screenplays.<axis> が確定したので、この台本を参照する
            # 全 video の experiment_assignments.observed_value を書く。
            try:
                n = _observed.back_fill_observed_for_screenplay(sp_id)
                if n:
                    logger.info(
                        "observed_value back-filled: sp=%s rows=%d", sp_id, n,
                    )
            except Exception as e:
                logger.warning(
                    "observed_value back-fill failed: sp=%s err=%s", sp_id, e,
                )
        except Exception as e:
            logger.warning("%s タグ付け失敗: %s", sp_id, e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
