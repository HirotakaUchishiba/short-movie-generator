#!/usr/bin/env python3
"""Stage 3 (背景画像) のグローバルキャッシュを LRU で削除する CLI。

容量上限を指定し、超過分を ``last_used_at`` の古い順に削除する。

例:
    python3 scripts/prune_bg_cache.py --max-bytes 50G
    python3 scripts/prune_bg_cache.py --max-bytes 10G --dry-run

cron 推奨運用 (毎日 4:00 に 50GB 制限):
    0 4 * * *  cd /path/to/repo && python3 scripts/prune_bg_cache.py --max-bytes 50G >> logs/prune.log 2>&1
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SUFFIX_FACTOR = {
    "K": 1024,
    "M": 1024 ** 2,
    "G": 1024 ** 3,
    "T": 1024 ** 4,
}


def _parse_size(s: str) -> int:
    """`50G` / `1024M` / `12345` を bytes に変換する。"""
    s = s.strip().upper()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KMGT]?)B?", s)
    if not m:
        raise argparse.ArgumentTypeError(f"size として解釈できません: {s!r}")
    val, suffix = m.group(1), m.group(2)
    return int(float(val) * _SUFFIX_FACTOR.get(suffix, 1))


def _fmt_bytes(n: int) -> str:
    for unit, factor in [("T", 1024 ** 4), ("G", 1024 ** 3),
                         ("M", 1024 ** 2), ("K", 1024)]:
        if n >= factor:
            return f"{n / factor:.1f}{unit}B"
    return f"{n}B"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-bytes", required=True, type=_parse_size,
                         help="許容する最大 byte 数 (例: 50G / 10000M)。"
                              "超過分が LRU で削除される")
    parser.add_argument("--dry-run", action="store_true",
                         help="実際には削除せず、削除対象だけ表示する")
    parser.add_argument("--verbose", "-v", action="store_true",
                         help="削除した key を 1 行ずつ出力する")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root))
    import bg_cache

    entries = bg_cache.list_entries()
    total_before = sum(e["size_bytes"] for e in entries)
    print(f"cache root: {bg_cache._cache_root()}")
    print(f"entries: {len(entries)}")
    print(f"total size: {_fmt_bytes(total_before)}")
    print(f"max-bytes:  {_fmt_bytes(args.max_bytes)}")

    if total_before <= args.max_bytes:
        print("→ no prune needed (under limit)")
        return 0

    res = bg_cache.prune(max_total_bytes=args.max_bytes, dry_run=args.dry_run)
    deleted = res["deleted"]
    freed = sum(d["size_bytes"] for d in deleted)
    action = "would delete" if args.dry_run else "deleted"
    print(f"→ {action} {len(deleted)} entries, {_fmt_bytes(freed)} freed")
    print(f"   total after: {_fmt_bytes(res['total_bytes_after'])}")

    if args.verbose:
        for d in deleted:
            print(f"   - {d['key']} ({_fmt_bytes(d['size_bytes'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
