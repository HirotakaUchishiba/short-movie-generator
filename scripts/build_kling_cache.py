#!/usr/bin/env python3
"""既存 ``temp/<TS>/kling_*.mp4`` を遡及的に kling_cache に seed する CLI。

過去 project の生成資産から cache を作り、新規 project での hit rate を
立ち上げるためのバックフィル。同じ cache key の entry が既にあれば skip。

例:
    python3 scripts/build_kling_cache.py
    python3 scripts/build_kling_cache.py --ts 20260420_153000
    python3 scripts/build_kling_cache.py --dry-run --verbose
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._cli_base import get_logger  # noqa: E402

logger = get_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ts", default=None,
                        help="指定 TS のみ処理 (デフォルト: 全 project)")
    parser.add_argument("--dry-run", action="store_true",
                        help="実際には store せず、対象を一覧表示")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    import config
    import kling_cache
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
            if args.verbose:
                logger.info("skip %s: no screenplay.json", ts_dir.name)
            continue
        try:
            sp = staged_pipeline.load_project_screenplay(str(ts_dir))
        except Exception as e:
            logger.error("failed to load %s: %s", ts_dir.name, e)
            failed += 1
            continue
        scenes = sp.get("scenes") or []
        for i, scene in enumerate(scenes):
            raw = ts_dir / f"kling_{i:03d}.mp4"
            if not raw.exists():
                continue
            try:
                inputs = scene_gen._scene_kling_inputs(
                    i, scene, sp, str(ts_dir))
            except Exception as e:
                logger.error(
                    "  %s scene %d: input build failed (%s)",
                    ts_dir.name, i, e,
                )
                failed += 1
                continue
            if inputs is None:
                continue
            if kling_cache.lookup(inputs["cache_key"]):
                skipped += 1
                if args.verbose:
                    logger.info(
                        "  %s scene %d: already cached (%s)",
                        ts_dir.name, i, inputs["cache_key"],
                    )
                continue
            meta = scene_gen._build_kling_cache_meta(scene, inputs)
            if args.dry_run:
                logger.info(
                    "  %s scene %d: would seed %s (%d bytes)",
                    ts_dir.name, i, inputs["cache_key"], raw.stat().st_size,
                )
                seeded += 1
                continue
            try:
                kling_cache.store(inputs["cache_key"], str(raw), meta)
                seeded += 1
                if args.verbose:
                    logger.info(
                        "  %s scene %d: seeded %s",
                        ts_dir.name, i, inputs["cache_key"],
                    )
            except Exception as e:
                logger.error(
                    "  %s scene %d: store failed (%s)",
                    ts_dir.name, i, e,
                )
                failed += 1

    logger.info(
        "seeded: %d, skipped (already cached): %d, failed: %d",
        seeded, skipped, failed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
