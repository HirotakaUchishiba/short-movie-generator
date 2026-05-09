#!/usr/bin/env python3
"""Stage 3 (背景画像) のグローバルキャッシュを一覧 / 統計表示する CLI。

例:
    python3 scripts/inspect_bg_cache.py
    python3 scripts/inspect_bg_cache.py --sort hits --top 30
    python3 scripts/inspect_bg_cache.py --location home_office
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


def _fmt_bytes(n: int) -> str:
    for unit, factor in [("T", 1024 ** 4), ("G", 1024 ** 3),
                         ("M", 1024 ** 2), ("K", 1024)]:
        if n >= factor:
            return f"{n / factor:.1f}{unit}B"
    return f"{n}B"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sort", choices=["last_used", "hits", "size",
                                            "created"],
                        default="last_used")
    parser.add_argument("--top", type=int, default=20,
                        help="表示する最大件数")
    parser.add_argument("--location", default=None,
                        help="location_ref で絞り込み")
    parser.add_argument("--blacklisted-only", action="store_true",
                        help="blacklist のみ表示")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root))
    import bg_cache

    entries = bg_cache.list_entries()
    if args.location:
        entries = [e for e in entries if e["location_ref"] == args.location]
    if args.blacklisted_only:
        entries = [e for e in entries
                    if (e.get("quality") or {}).get("blacklisted")]

    total_size = sum(e["size_bytes"] for e in entries)
    total_hits = sum(e["hit_count"] for e in entries)

    print(f"cache root: {bg_cache._cache_root()}")
    print(f"entries: {len(entries)}")
    print(f"total size: {_fmt_bytes(total_size)}")
    print(f"total hits: {total_hits}")
    by_loc = Counter(e["location_ref"] or "_unscoped" for e in entries)
    print("\nlocation 分布:")
    for loc, n in by_loc.most_common():
        print(f"  {loc:<30s} {n}")

    sort_key = {
        "last_used": lambda e: e["last_used_at"] or "",
        "hits": lambda e: -e["hit_count"],
        "size": lambda e: -e["size_bytes"],
        "created": lambda e: e["created_at"] or "",
    }[args.sort]
    if args.sort == "last_used":
        entries.sort(key=sort_key, reverse=True)
    else:
        entries.sort(key=sort_key)

    print(f"\nTop {args.top} (sort={args.sort}):")
    print(f"{'key':<18} {'size':>8} {'hits':>5} {'cam':>14} "
          f"{'loc':<20} {'last_used':<22}")
    for e in entries[:args.top]:
        q = e.get("quality") or {}
        flag = "B" if q.get("blacklisted") else (
            "F" if q.get("final_render_completed") else " ")
        print(f"{e['key']:<18} {_fmt_bytes(e['size_bytes']):>8} "
              f"{e['hit_count']:>5} {(e.get('camera_distance') or '-'):>14} "
              f"{(e['location_ref'] or '-'):<20} "
              f"{(e['last_used_at'] or '-'):<22} {flag}")
    print("\nflags: B=blacklisted, F=final_render_completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
