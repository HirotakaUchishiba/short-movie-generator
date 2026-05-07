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
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
import config  # noqa: E402
from analytics import db  # noqa: E402

logger = logging.getLogger(__name__)

TABLES: tuple[str, ...] = (
    "generation_records",
    "experiment_assignments",
    "qa_failures",
    "videos",
    "posts",
    "post_metrics",
    "screenplays",
)


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
        for table in TABLES:
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


def main() -> int:
    log_setup.setup()
    parser = argparse.ArgumentParser(prog="audit_freeze")
    parser.add_argument("--since", help="YYYY-MM-DD 以降の行のみ凍結")
    parser.add_argument("--out-dir",
                        help="既定: data/audit_freezes/<YYYY-MM-DD_HHMMSS>/")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else default_out_dir()
    counts = freeze_tables(out_dir, since=args.since)

    print(f"[audit-freeze] dir: {out_dir}")
    for table, n in counts.items():
        print(f"  {table}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
