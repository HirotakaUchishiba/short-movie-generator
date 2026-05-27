"""24h 自律稼働ランナー: URL キューを消化し auto_loop を回し続ける。

    python3 scripts/autonomous_runner.py [--poll 300] [--dry-run] [--once]

while ループで (1) STOP ファイル / budget cap を確認 → (2) next_pending →
(3) run_one_video → (4) mark done/failed → (5) sleep。1 動画の失敗
(AutoLoopAborted) は failed 記録で次へ継続。BudgetExceeded / STOP ファイル /
--once / キュー空で終了する。

予算ガード・kill switch・通知は auto_loop / cost_tracking の既存機構を再利用し、
本ランナーは「入力供給 + ループ」だけを担う。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from autonomous import task_queue  # noqa: E402
from cost_tracking import budget  # noqa: E402

logger = logging.getLogger(__name__)

STOP_FILE = "AUTONOMOUS_STOP"


def _kill_requested() -> bool:
    return os.path.exists(os.path.join(config.BASE_DIR, STOP_FILE))


def _budget_blocked() -> bool:
    try:
        budget.assert_within_caps()
        return False
    except budget.BudgetExceeded as e:
        logger.warning("[autonomous] budget cap reached: %s", e)
        return True


def run_loop(*, poll: float = 300.0, dry_run: bool = False,
             once: bool = False, drain: bool = False, run_video=None) -> int:
    """キューを消化し、処理した動画数を返す。

    - ``once``: 1 ジョブ処理 (or キュー空) で終了。
    - ``drain``: キューが空になるまで処理して終了 (= cron 定期起動向け)。
    - どちらも False (= 常駐): キュー空でも sleep して新規ジョブを待ち続ける。

    ``run_video`` はテスト用 DI (= 既定で auto_loop.run_one_video)。
    """
    from scripts.auto_loop import AutoLoopAborted
    if run_video is None:
        from scripts.auto_loop import run_one_video
        run_video = run_one_video

    processed = 0
    while True:
        if _kill_requested():
            logger.info("[autonomous] STOP file detected -> exit")
            break
        if _budget_blocked():
            logger.info("[autonomous] budget blocked -> exit")
            break
        job = task_queue.next_pending()
        if job is None:
            if once or drain:
                break
            logger.info("[autonomous] queue empty -> sleep %.0fs", poll)
            time.sleep(poll)
            continue
        try:
            ts = run_video(job["url"], license_status=job["license"],
                           dry_run=dry_run)
            task_queue.mark(job["id"], "done", ts=ts)
            processed += 1
            logger.info("[autonomous] job %s done ts=%s", job["id"], ts)
        except AutoLoopAborted as e:
            task_queue.mark(job["id"], "failed", error=str(e))
            logger.warning("[autonomous] job %s failed: %s", job["id"], e)
        except budget.BudgetExceeded as e:
            logger.info("[autonomous] budget exceeded mid-run -> exit: %s", e)
            break
        except Exception as e:  # noqa: BLE001  (1 件の予期せぬ失敗で全体を止めない)
            task_queue.mark(job["id"], "failed", error=f"unexpected: {e}")
            logger.exception("[autonomous] job %s unexpected error", job["id"])
        if once:
            break
    logger.info("[autonomous] loop ended, processed=%d", processed)
    return processed


def main() -> int:
    import log_setup
    log_setup.setup()
    parser = argparse.ArgumentParser(prog="autonomous_runner")
    parser.add_argument("--poll", type=float, default=300.0,
                        help="キュー空のときの待機秒数")
    parser.add_argument("--dry-run", action="store_true",
                        help="publish 直前で停止 (auto_loop に伝播)")
    parser.add_argument("--once", action="store_true",
                        help="1 ジョブ処理 or キュー空で終了")
    parser.add_argument("--drain", action="store_true",
                        help="キューを空になるまで処理して終了 (= cron 定期起動向け)")
    args = parser.parse_args()
    run_loop(poll=args.poll, dry_run=args.dry_run, once=args.once,
             drain=args.drain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
