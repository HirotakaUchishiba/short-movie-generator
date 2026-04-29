#!/usr/bin/env python3
"""生成した動画(output/reels_<TS>.mp4)をAnalytics DBに登録する。

使い方:
    python3 scripts/ingest_video.py 20260425_123456 --cost 18.3
"""
import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import log_setup  # noqa: E402
from analytics import db  # noqa: E402

log_setup.setup()
logger = logging.getLogger(__name__)


def _ffprobe_duration(path: str) -> float | None:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True, check=True,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="生成動画をDBに登録")
    parser.add_argument("timestamp", help="生成時のtimestamp (例 20260425_123456)")
    parser.add_argument("--cost", type=float, help="生成コスト USD")
    args = parser.parse_args()

    ts = args.timestamp
    temp_dir = Path(config.TEMP_DIR) / ts
    output_path = Path(config.OUTPUT_DIR) / f"reels_{ts}.mp4"
    metadata_path = temp_dir / "metadata.json"

    if not output_path.exists():
        logger.error("動画が見つかりません: %s", output_path)
        return 1
    if not metadata_path.exists():
        logger.error("metadata.jsonが見つかりません: %s", metadata_path)
        return 1

    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    screenplay_path = Path(config.BASE_DIR) / meta["screenplay_path"]
    db.init_db()
    sp_id = db.upsert_screenplay(str(screenplay_path))

    cost = args.cost

    duration = _ffprobe_duration(str(output_path))

    db.insert_video(
        video_id=ts,
        screenplay_id=sp_id,
        output_path=str(output_path),
        duration_sec=duration,
        generation_cost_usd=cost,
    )
    logger.info("video %s 登録完了 (screenplay=%s, duration=%.1fs, cost=$%.2f)",
                ts, sp_id, duration or 0, cost or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
