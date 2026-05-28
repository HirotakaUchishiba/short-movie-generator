#!/usr/bin/env python3
import argparse
import logging
import os
import sys
from datetime import datetime

import config
import log_setup
import progress_store
import staged_pipeline

log_setup.setup()
logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="段階的ゲート方式の動画生成 CLI",
    )
    p.add_argument("screenplay_name", nargs="?",
                   help="台本ファイル名 (拡張子省略可)")
    p.add_argument("--resume", dest="resume_ts", metavar="TS",
                   help="既存 TS の次 stage を実行")
    return p


def _print_screenplays() -> None:
    if not os.path.isdir(config.SCREENPLAYS_DIR):
        return
    names = sorted(f for f in os.listdir(config.SCREENPLAYS_DIR) if f.endswith(".json"))
    if names:
        print(f"\n台本ディレクトリ: {config.SCREENPLAYS_DIR}")
        print("利用可能な台本:")
        for n in names:
            print(f"  - {n}")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.screenplay_name:
        parser.print_help()
        _print_screenplays()
        sys.exit(1)

    _run_pipeline(args.screenplay_name, args.resume_ts)


def _run_pipeline(screenplay_name: str, resume_ts: str | None) -> None:
    ts = resume_ts or datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    ts_path = os.path.join(config.TEMP_DIR, ts)
    os.makedirs(ts_path, exist_ok=True)

    # Stage 1 が既に走っていれば project snapshot を SSOT として読む
    # (= UI 編集や analyze 由来 compose 結果を CLI からも反映)。
    # 未実行なら template から立ち上げる (= 新規 project / Stage 1 起動経路)。
    if progress_store.is_generated(ts_path, "script"):
        screenplay = staged_pipeline.load_project_screenplay(ts_path)
        logger.info("台本: %s (snapshot) | TS: %s", screenplay_name, ts)
    else:
        screenplay = staged_pipeline.load_template(screenplay_name)
        logger.info("台本: %s (template) | TS: %s", screenplay_name, ts)

    nxt = progress_store.next_stage(ts_path)
    cur = progress_store.current_stage(ts_path)

    if nxt is None:
        if cur is None:
            logger.info("全 stage 完了済み — 動画は output/reels_%s.mp4 にあります", ts)
            return
        logger.info(
            "stage '%s' は生成済みですが未承認です。"
            "プレビューUIで承認してください: %s",
            cur, _ui_url(ts),
        )
        return

    logger.info("実行stage: %s", nxt)
    try:
        executed = staged_pipeline.run_next_stage(screenplay, screenplay_name, ts_path)
    except Exception as e:
        logger.exception("stage実行エラー: %s", e)
        sys.exit(1)

    if executed == "download":
        logger.info(
            "動画完成 — プレビューUIでダウンロードできます: %s",
            _ui_url(ts),
        )
    else:
        logger.info(
            "stage '%s' 生成完了。プレビューUIで確認・承認してください: %s",
            executed, _ui_url(ts),
        )
        logger.info("承認後 `python main.py %s --resume %s` で次stage実行",
                    screenplay_name, ts)


def _ui_url(ts: str) -> str:
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("PREVIEW_PORT", "5555"))
    return f"http://{host}:{port}/project/{ts}"


if __name__ == "__main__":
    main()
