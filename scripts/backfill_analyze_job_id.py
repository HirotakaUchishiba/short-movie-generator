"""既存プロジェクトの metadata.json に analyze_job_id を後付けする。

Stage 1「素材編集」セクションは metadata.json の analyze_job_id 有無で
表示が切り替わる。Phase A (analyze_job_id 永続化対応) より前に作成された
プロジェクトは値が空なので、analytics.db の analyze_jobs テーブルから
screenplay 名で逆引きして書き戻す。

冪等。analyze_job_id が既にあるプロジェクトはスキップ。dry-run 既定。
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
        print(f"temp_dir が存在しません: {temp_dir}", file=sys.stderr)
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
            print(f"[skip] {ts_dir.name}: invalid json ({e})")
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
            print(f"[apply ] {ts_dir.name} ← {job_id}")
        else:
            print(f"[dryrun] {ts_dir.name} ← {job_id}")
        updated += 1

    mode = "apply" if args.apply else "dry-run"
    print(
        f"\n[{mode}] backfill候補 {updated} 件 / "
        f"既に紐付済 {skipped_already} 件 / "
        f"対応 analyze_job 無し {skipped_no_match} 件",
    )
    if not args.apply and updated > 0:
        print("実行するには --apply を付けてください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
