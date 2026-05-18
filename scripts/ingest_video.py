#!/usr/bin/env python3
"""生成した動画(output/reels_<TS>.mp4)をAnalytics DBに登録する。

使い方:
    python3 scripts/ingest_video.py 20260425_123456 --cost 18.3
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from analytics import db  # noqa: E402
from improvement import observed as _observed  # noqa: E402
from scripts._cli_base import get_logger  # noqa: E402

logger = get_logger(__name__)


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
    parser.add_argument(
        "--prefer", choices=["final", "raw"], default="final",
        help="canonical final と pipeline raw のどちらを優先するか (既定: final)",
    )
    args = parser.parse_args()

    ts = args.timestamp
    temp_dir = Path(config.TEMP_DIR) / ts
    raw_path = Path(config.OUTPUT_DIR) / f"reels_{ts}.mp4"
    metadata_path = temp_dir / "metadata.json"

    if not metadata_path.exists():
        logger.error("metadata.jsonが見つかりません: %s", metadata_path)
        return 1

    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    output_path: Path
    final_meta: dict | None = None
    if args.prefer == "final":
        final_meta = _canonical_final(meta)
        if final_meta:
            output_path = temp_dir / "final" / final_meta["filename"]
        else:
            output_path = raw_path
    else:
        output_path = raw_path

    if not output_path.exists():
        logger.error("動画が見つかりません: %s", output_path)
        return 1

    # screenplay は project snapshot を直接登録する (= 旧 template path 同様 sha256 で一意)
    screenplay_path = (Path(config.BASE_DIR) / temp_dir / meta["screenplay_path"]
                       if not Path(meta["screenplay_path"]).is_absolute()
                       else Path(meta["screenplay_path"]))
    if not screenplay_path.exists():
        # 旧形式 (= screenplays/<name>.json をフルパスで持っていた時代) のフォールバック
        screenplay_path = Path(config.BASE_DIR) / meta["screenplay_path"]
    db.init_db()
    sp_id = db.upsert_screenplay(str(screenplay_path))

    cost = args.cost
    duration = _ffprobe_duration(str(output_path))

    video_id = ts  # 現状は video_id == ts。将来 sha256[:12] へ移行した時は
                   # ここで派生させる。
    db.insert_video(
        video_id=video_id,
        screenplay_id=sp_id,
        output_path=str(output_path),
        duration_sec=duration,
        generation_cost_usd=cost,
        final_imported=bool(final_meta),
        final_filename=final_meta["filename"] if final_meta else None,
        final_audio_match_score=(
            final_meta.get("audio_match_score") if final_meta else None
        ),
    )
    # Phase 3 で auto_loop が experiment_assignments に書き込んだ ts ベースの
    # 行を canonical な videos.id に揃える。video_id == ts の間は no-op。
    migrated = db.backfill_experiment_assignments_video_id(
        ts=ts, video_id=video_id,
    )
    if migrated and video_id != ts:
        logger.info(
            "experiment_assignments backfill: %d rows ts=%s → video_id=%s",
            migrated, ts, video_id,
        )
    logger.info(
        "video %s 登録完了 (screenplay=%s, source=%s, duration=%.1fs, cost=$%.2f)",
        video_id, sp_id, "final" if final_meta else "raw",
        duration or 0, cost or 0,
    )
    # video が DB に乗ったので、Phase 3 の experiment_assignments に observed_value
    # を書ける (= screenplay が事前に auto_tag されていなければ何も入らないが、
    # ingest_screenplay 側からも back-fill が走るので最終的には埋まる)。
    try:
        n = _observed.back_fill_observed_for_ts(ts)
        if n:
            logger.info("observed_value back-filled: ts=%s rows=%d", ts, n)
    except Exception as e:
        logger.warning("observed_value back-fill failed: ts=%s err=%s", ts, e)
    return 0


def _canonical_final(meta: dict) -> dict | None:
    for v in meta.get("final_versions") or []:
        if v.get("is_canonical"):
            return v
    return None


if __name__ == "__main__":
    sys.exit(main())
