"""既存プロジェクトの metadata.json に analyze_job_id を後付けする。

Stage 1「素材編集」セクションは metadata.json の analyze_job_id 有無で
表示が切り替わる。Phase A (analyze_job_id 永続化対応) より前に作成された
プロジェクトは値が空なので、analytics.db の analyze_jobs テーブルから
screenplay 名で逆引きして書き戻す。

冪等。analyze_job_id が既にあるプロジェクトはスキップ。dry-run 既定。

使い方:
    python3 scripts/backfill_analyze_job_id.py            # dry-run
    python3 scripts/backfill_analyze_job_id.py --apply    # 実際に書き戻し
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from analytics import db as _db  # noqa: E402
from scripts._cli_base import get_logger  # noqa: E402

logger = get_logger("backfill_analyze_job_id")


def find_job_id_for_screenplay(name: str) -> str | None:
    """screenplay basename と一致する analyze_jobs.id を返す (最新優先)。"""
    with _db.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, screenplay_path FROM analyze_jobs
               WHERE status = 'completed'
               ORDER BY created_at DESC""",
        ).fetchall()
    for r in rows:
        if not r["screenplay_path"]:
            continue
        if os.path.basename(r["screenplay_path"]) == name:
            return r["id"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="実際に metadata.json を書き換える (既定は dry-run)",
    )
    args = parser.parse_args()

    temp_dir = Path(config.TEMP_DIR)
    if not temp_dir.is_dir():
        logger.error("temp_dir が存在しません: %s", temp_dir)
        return 1

    updated = 0
    skipped_already = 0
    skipped_no_match = 0
    for ts_dir in sorted(temp_dir.iterdir()):
        meta_path = ts_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning("[skip] %s: invalid json (%s)", ts_dir.name, e)
            continue
        if meta.get("analyze_job_id"):
            skipped_already += 1
            continue
        name = meta.get("screenplay_name") or ""
        job_id = find_job_id_for_screenplay(name)
        if not job_id:
            skipped_no_match += 1
            continue
        if args.apply:
            meta["analyze_job_id"] = job_id
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            logger.info("[apply ] %s ← %s", ts_dir.name, job_id)
        else:
            logger.info("[dryrun] %s ← %s", ts_dir.name, job_id)
        updated += 1

    mode = "apply" if args.apply else "dry-run"
    logger.info(
        "[%s] backfill候補 %d 件 / 既に紐付済 %d 件 / 対応 analyze_job 無し %d 件",
        mode, updated, skipped_already, skipped_no_match,
    )
    if not args.apply and updated > 0:
        logger.info("実行するには --apply を付けてください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
