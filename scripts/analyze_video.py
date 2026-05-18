#!/usr/bin/env python3
"""参考動画をClaude Opus 4.7で分析し、screenplays/auto_<name>.json を生成する。

実体は analyze.pipeline.run() に集約。本スクリプトは argparse → run() の
薄いラッパーで、UI ジョブ runner と同じロジックを共有する。

使い方:
    python3 scripts/analyze_video.py path/to/reference.mov
    python3 scripts/analyze_video.py path/to/reference.mov --output my_output.json
    python3 scripts/analyze_video.py path/to/reference.mov --fps 2.0
"""
import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

from analyze import AnalyzeCancelled, AnalyzeOptions, run  # noqa: E402
from scripts._cli_base import get_logger  # noqa: E402

logger = get_logger(__name__)


def _log_progress(event: str, data: dict) -> None:
    if event == "phase_start":
        logger.info("→ phase: %s", data.get("phase"))
    elif event == "phase_complete":
        phase = data.get("phase")
        rest = {k: v for k, v in data.items() if k != "phase"}
        if rest:
            logger.info("  ✓ %s %s", phase, rest)
        else:
            logger.info("  ✓ %s", phase)
    elif event == "completed":
        logger.info("台本保存: %s", data.get("output_path"))
        logger.info("  scenes=%d, lines=%d, duration=%.1fs",
                    data.get("scenes", 0),
                    data.get("lines", 0),
                    data.get("duration_sec", 0))


def main() -> int:
    parser = argparse.ArgumentParser(description="参考動画を分析して台本JSONを生成")
    parser.add_argument("video_path", help="分析する動画ファイル")
    parser.add_argument("--output", help="出力先JSONパス (既定: screenplays/auto_<名前>.json)")
    parser.add_argument("--fps", type=float, default=2.0,
                        help="フレーム抽出レート [既定 2.0 = 0.5秒刻み]")
    parser.add_argument("--keep-tmp", action="store_true",
                        help="一時フレーム・音声を削除しない (デバッグ用)")
    args = parser.parse_args()

    options = AnalyzeOptions(fps=args.fps)

    try:
        run(
            video_path=args.video_path,
            output_path=args.output,
            options=options,
            keep_tmp=args.keep_tmp,
            on_progress=_log_progress,
        )
        return 0
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except AnalyzeCancelled:
        logger.warning("分析がキャンセルされました")
        return 130


if __name__ == "__main__":
    sys.exit(main())
