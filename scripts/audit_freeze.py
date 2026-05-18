#!/usr/bin/env python3
"""Phase 4: 本番展開後の監査ログを凍結保存する。

`generation_records` / `experiment_assignments` / `qa_failures` /
`videos` / `posts` / `post_metrics` / `screenplays` の現在状態を
``data/audit_freezes/<YYYY-MM-DD_HHMMSS>/`` 配下に JSONL でダンプする。

後で削除請求 / 規約違反対応 / クレーム対応の際に「あの時点で何を公開
していたか / どの prompt + seed で生成したか」を追えるようにするのが
眼目。`since` 引数で日付範囲を絞れる (= 1 ヶ月分だけ凍結したい場合等)。

使い方:
    python3 scripts/audit_freeze.py
    python3 scripts/audit_freeze.py --since 2026-05-01
    python3 scripts/audit_freeze.py --out-dir /backup/audit/2026-05
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
import config  # noqa: E402
from analytics import db  # noqa: E402

logger = logging.getLogger(__name__)

# View / SQLite 内部テーブルは除外。新テーブルが schema に追加されると
# 自動で freeze 対象になる (= 手動メンテナンスが要らない)。
_EXCLUDED_TABLES: frozenset[str] = frozenset({
    "schema_version",  # スキーマ履歴は _metadata.json に snapshot 済み
})


def _list_tables(conn) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name",
    ).fetchall()
    return [r["name"] for r in rows if r["name"] not in _EXCLUDED_TABLES]


def _table_columns(conn, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def freeze_tables(out_dir: Path, *, since: str | None = None) -> dict[str, int]:
    """``out_dir`` 配下に各テーブルを ``<table>.jsonl`` で書き出す。

    Args:
        out_dir: 出力先ディレクトリ。
        since: ``YYYY-MM-DD`` 形式で指定すると ``created_at >= since`` の
            行のみ。``created_at`` カラムを持つテーブルだけに適用される。

    Returns:
        ``{table_name: row_count}``
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with db.get_connection() as conn:
        for table in _list_tables(conn):
            cols = _table_columns(conn, table)
            sql = f"SELECT * FROM {table}"
            params: tuple = ()
            if since and "created_at" in cols:
                sql += " WHERE created_at >= ?"
                params = (since,)
            elif since and "registered_at" in cols:
                # posts は created_at が無く registered_at がある
                sql += " WHERE registered_at >= ?"
                params = (since,)
            rows = conn.execute(sql, params).fetchall()
            path = out_dir / f"{table}.jsonl"
            with open(path, "w") as f:
                for r in rows:
                    f.write(json.dumps(dict(r), ensure_ascii=False,
                                       default=str) + "\n")
            counts[table] = len(rows)

    metadata = {
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "since": since,
        "schema_version": db.CURRENT_SCHEMA_VERSION,
        "row_counts": counts,
    }
    with open(out_dir / "_metadata.json", "w") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    return counts


def default_out_dir() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    return Path(config.BASE_DIR) / "data" / "audit_freezes" / ts


_FREEZE_DIR_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$")


def _parse_freeze_dir_date(name: str) -> datetime | None:
    """Freeze ディレクトリ名 ``YYYY-MM-DD_HHMMSS`` から datetime を返す。"""
    m = _FREEZE_DIR_RE.match(name)
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3]),
                        int(m[4]), int(m[5]), int(m[6]),
                        tzinfo=timezone.utc)
    except ValueError:
        return None


def rotate_old_freezes(base_dir: Path | None = None, *,
                       rotate_after_days: int,
                       now: datetime | None = None) -> dict[str, int]:
    """``rotate_after_days`` 日経過した freeze を月別 tar.gz に固めて元 dir を削除。

    アーカイブ先: ``<base_dir>/_archive/<YYYY-MM>.tar.gz``。同月の追加は append 不可
    なので、新たに固めるべき freeze がある場合は既存 tar.gz の中身を一旦展開して
    再 tar することはせず、月別に **複数の tar.gz** が積まれる設計
    (= ``2026-05.tar.gz`` ``2026-05_2.tar.gz`` …)。十分シンプル + idempotent。

    Returns:
        ``{"archived": N, "deleted": N, "skipped": N}``
    """
    base = Path(base_dir) if base_dir else (
        Path(config.BASE_DIR) / "data" / "audit_freezes"
    )
    if not base.exists():
        return {"archived": 0, "deleted": 0, "skipped": 0}
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(
        days=int(rotate_after_days),
    )
    archive_dir = base / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    by_month: dict[str, list[Path]] = {}
    skipped = 0
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name == "_archive":
            continue
        d = _parse_freeze_dir_date(child.name)
        if d is None:
            skipped += 1
            continue
        if d > cutoff:
            continue
        key = d.strftime("%Y-%m")
        by_month.setdefault(key, []).append(child)

    archived = 0
    deleted = 0
    for month, dirs in sorted(by_month.items()):
        target = archive_dir / f"{month}.tar.gz"
        suffix = 2
        while target.exists():
            target = archive_dir / f"{month}_{suffix}.tar.gz"
            suffix += 1
        with tarfile.open(target, "w:gz") as tf:
            for d in dirs:
                tf.add(d, arcname=d.name)
                archived += 1
        for d in dirs:
            shutil.rmtree(d)
            deleted += 1
        logger.info("[audit-freeze] rotated %d freezes → %s",
                    len(dirs), target.name)
    return {"archived": archived, "deleted": deleted, "skipped": skipped}


def main() -> int:
    log_setup.setup()
    parser = argparse.ArgumentParser(prog="audit_freeze")
    parser.add_argument("--since", help="YYYY-MM-DD 以降の行のみ凍結")
    parser.add_argument("--out-dir",
                        help="既定: data/audit_freezes/<YYYY-MM-DD_HHMMSS>/")
    parser.add_argument(
        "--rotate-after-days", type=int, default=0,
        help="N 日以上経過した既存 freeze を月別 tar.gz に固めて元 dir を削除 "
             "(0 = ローテーションしない、既定)。新規 freeze は --skip-freeze 指定時を除き並行実行される。",
    )
    parser.add_argument(
        "--skip-freeze", action="store_true",
        help="新規 freeze を作らずローテーションのみ実行する (= cron 専用モード)",
    )
    args = parser.parse_args()

    if not args.skip_freeze:
        out_dir = Path(args.out_dir) if args.out_dir else default_out_dir()
        counts = freeze_tables(out_dir, since=args.since)
        logger.info("[audit-freeze] dir: %s", out_dir)
        for table, n in counts.items():
            logger.info("  %s: %d", table, n)

    if args.rotate_after_days > 0:
        result = rotate_old_freezes(rotate_after_days=args.rotate_after_days)
        logger.info(
            "[audit-freeze] rotate (>%d days): archived=%d deleted=%d skipped=%d",
            args.rotate_after_days,
            result["archived"], result["deleted"], result["skipped"],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
