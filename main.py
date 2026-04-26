#!/usr/bin/env python3
import json
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


def _print_usage() -> None:
    print("使い方:")
    print("  python main.py <台本>                次stageを1つだけ実行 (新規TS自動生成)")
    print("  python main.py <台本> --resume <TS>  既存TSの次stageを実行")
    print(f"\n台本ディレクトリ: {config.SCREENPLAYS_DIR}")
    if os.path.isdir(config.SCREENPLAYS_DIR):
        names = sorted(f for f in os.listdir(config.SCREENPLAYS_DIR) if f.endswith(".json"))
        if names:
            print("利用可能な台本:")
            for n in names:
                print(f"  - {n}")
    sys.exit(1)


def _parse_args() -> dict:
    args = {"screenplay_name": None, "resume_ts": None}
    positional: list[str] = []
    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--resume" and i + 1 < len(sys.argv):
            args["resume_ts"] = sys.argv[i + 1]
            i += 2
        else:
            positional.append(a)
            i += 1
    if positional:
        args["screenplay_name"] = positional[0]
    return args


def main() -> None:
    if len(sys.argv) < 2:
        _print_usage()

    args = _parse_args()
    if not args["screenplay_name"]:
        _print_usage()

    screenplay_name = args["screenplay_name"]
    ts = args["resume_ts"] or datetime.now().strftime("%Y%m%d_%H%M%S")

    os.makedirs(config.TEMP_DIR, exist_ok=True)
    ts_path = os.path.join(config.TEMP_DIR, ts)
    os.makedirs(ts_path, exist_ok=True)

    screenplay = staged_pipeline.load_screenplay(screenplay_name)
    logger.info("台本: %s | TS: %s", screenplay_name, ts)

    nxt = progress_store.next_stage(ts_path)
    cur = progress_store.current_stage(ts_path)

    if nxt is None:
        if cur is None:
            logger.info("全stage完了済み — 何もすることがありません")
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

    if executed == "final":
        logger.info("動画完成しました")
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
