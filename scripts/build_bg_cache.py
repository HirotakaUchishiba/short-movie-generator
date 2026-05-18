#!/usr/bin/env python3
"""既存 ``temp/<TS>/bg_*.png`` を遡及的に bg_cache に seed する CLI。

過去 project の生成資産から cache を作り、新規 project での hit rate を
立ち上げるためのバックフィル。同じ cache key の entry が既にあれば skip。

例:
    python3 scripts/build_bg_cache.py
    python3 scripts/build_bg_cache.py --ts 20260420_153000
    python3 scripts/build_bg_cache.py --dry-run --verbose
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts._cli_base import get_logger  # noqa: E402

logger = get_logger("build_bg_cache")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ts", default=None,
                        help="指定 TS のみ処理 (デフォルト: 全 project)")
    parser.add_argument("--dry-run", action="store_true",
                        help="実際には store せず、対象を一覧表示")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    import bg_cache
    import config
    import scene_gen
    import staged_pipeline

    temp_dir = Path(config.TEMP_DIR)
    if not temp_dir.exists():
        logger.error("temp_dir が存在しません: %s", temp_dir)
        return 1

    if args.ts:
        ts_dirs = [temp_dir / args.ts]
    else:
        ts_dirs = sorted(p for p in temp_dir.iterdir() if p.is_dir())

    seeded = 0
    skipped = 0
    failed = 0
    for ts_dir in ts_dirs:
        sp_path = ts_dir / "screenplay.json"
        if not sp_path.exists():
            logger.debug("skip %s: no screenplay.json", ts_dir.name)
            continue
        try:
            sp = staged_pipeline.load_project_screenplay(str(ts_dir))
        except Exception as e:
            logger.error("failed to load %s: %s", ts_dir.name, e)
            failed += 1
            continue
        scenes = sp.get("scenes") or []
        for i, scene in enumerate(scenes):
            png = ts_dir / f"bg_{i:03d}.png"
            if not png.exists():
                continue
            try:
                inputs = scene_gen._scene_bg_inputs(
                    i, scene, sp, str(ts_dir))
            except Exception as e:
                logger.error("  %s scene %d: input build failed (%s)",
                             ts_dir.name, i, e)
                failed += 1
                continue
            if inputs is None:
                continue
            if bg_cache.lookup(inputs["cache_key"]):
                skipped += 1
                logger.debug(
                    "  %s scene %d: already cached (%s)",
                    ts_dir.name, i, inputs["cache_key"],
                )
                continue
            meta = scene_gen._build_bg_cache_meta(scene, i, inputs)
            if args.dry_run:
                logger.info(
                    "  %s scene %d: would seed %s (%d bytes)",
                    ts_dir.name, i, inputs["cache_key"], png.stat().st_size,
                )
                seeded += 1
                continue
            try:
                bg_cache.store(inputs["cache_key"], str(png), meta)
                seeded += 1
                logger.debug(
                    "  %s scene %d: seeded %s",
                    ts_dir.name, i, inputs["cache_key"],
                )
            except Exception as e:
                logger.error("  %s scene %d: store failed (%s)",
                             ts_dir.name, i, e)
                failed += 1

    logger.info("seeded: %d, skipped (already cached): %d, failed: %d",
                seeded, skipped, failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
