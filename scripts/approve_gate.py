#!/usr/bin/env python3
"""Phase 4: PRODUCTION_HUMAN_GATE_ENABLED で停止中の auto_loop project を承認 → publish する。

使い方:
    python3 scripts/approve_gate.py                # 承認待ち一覧を表示
    python3 scripts/approve_gate.py <TS>           # 1 件を承認 + publish
    python3 scripts/approve_gate.py <TS> --reject  # 承認せず却下 (= status=auto_rejected)

承認対象:
    `generation_records.status = 'awaiting_human_gate'` の TS。auto_loop が
    `config.PRODUCTION_HUMAN_GATE_ENABLED=1` で publish 直前に停止し、Slack 通知
    した状態が起点。

承認 → publish の経路:
    final_import.publish.publish(ts, "youtube", privacy=privacy) を直接呼ぶ。
    publish 成功で generation_record を `status="completed"` に進める。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
from analytics import db as _adb  # noqa: E402
from notify import notify_slack  # noqa: E402

logger = logging.getLogger(__name__)


def list_awaiting() -> list[dict]:
    """``status='awaiting_human_gate'`` の generation_record を返す。"""
    with _adb.get_connection() as conn:
        rows = conn.execute(
            "SELECT ts, status, total_cost_usd, created_at "
            "FROM generation_records "
            "WHERE status = 'awaiting_human_gate' "
            "ORDER BY created_at DESC",
        ).fetchall()
    return [dict(r) for r in rows]


def approve_and_publish(ts: str, *, privacy: str = "unlisted") -> dict:
    """gate 中の TS を publish する。

    ``privacy='public'`` でも ``AUTO_LOOP_ALLOW_PUBLIC=0`` の間は
    youtube._resolve_privacy が unlisted に降格するので二重防衛は維持される。
    """
    rows = list_awaiting()
    if not any(r["ts"] == ts for r in rows):
        raise ValueError(
            f"{ts} は awaiting_human_gate 状態ではありません — 既に publish 済 / 却下 / 存在しない",
        )

    from final_import.publish import publish
    result = publish(ts, "youtube", privacy=privacy)
    _adb.update_generation_record(ts, status="completed")
    notify_slack(
        "info",
        f"approve_gate published: ts={ts}",
        context={
            "url": result.get("url") or "",
            "video_id": result.get("video_id") or "",
            "privacy": privacy,
        },
    )
    return result


def reject(ts: str, *, reason: str | None = None) -> None:
    rows = list_awaiting()
    if not any(r["ts"] == ts for r in rows):
        raise ValueError(
            f"{ts} は awaiting_human_gate 状態ではありません",
        )
    _adb.update_generation_record(ts, status="auto_rejected")
    notify_slack(
        "warning",
        f"approve_gate rejected: ts={ts} reason={reason or '-'}",
        context={"ts": ts},
    )


def _print_awaiting() -> int:
    rows = list_awaiting()
    if not rows:
        logger.info("[approve_gate] 承認待ちなし")
        return 0
    logger.info("[approve_gate] 承認待ち %d 件:", len(rows))
    for r in rows:
        cost = r.get("total_cost_usd")
        cost_str = f"${cost:.2f}" if cost is not None else "-"
        logger.info("  %s  cost=%s  created=%s",
                    r["ts"], cost_str, r.get("created_at") or "-")
    return 0


def main() -> int:
    log_setup.setup()
    parser = argparse.ArgumentParser(prog="approve_gate")
    parser.add_argument(
        "ts", nargs="?",
        help="承認 / 却下する TS。省略すると承認待ち一覧を表示。",
    )
    parser.add_argument(
        "--reject", action="store_true",
        help="承認せず却下する (= status=auto_rejected)",
    )
    parser.add_argument(
        "--privacy", default="unlisted",
        choices=("private", "unlisted", "public"),
        help="承認時の privacy (既定 unlisted、AUTO_LOOP_ALLOW_PUBLIC=0 で public は降格)",
    )
    parser.add_argument(
        "--reason", help="却下理由 (Slack 通知に載る)",
    )
    args = parser.parse_args()

    if args.ts is None:
        return _print_awaiting()

    try:
        if args.reject:
            reject(args.ts, reason=args.reason)
            logger.info("[approve_gate] rejected: ts=%s", args.ts)
        else:
            result = approve_and_publish(args.ts, privacy=args.privacy)
            logger.info(
                "[approve_gate] published: ts=%s video_id=%s url=%s",
                args.ts, result.get("video_id"), result.get("url"),
            )
    except ValueError as e:
        logger.error(str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
