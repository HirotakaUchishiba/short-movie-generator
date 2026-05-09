"""``/api/analytics/pending(/sync)`` の Blueprint。

`preview_server.py` から段階移行 (= cost に続く 2 番目)。`pending_queue.replay`
+ `finalize_pending_publish` を HTTP API として expose し、UI の
ProjectList の同期保留 badge から呼ばれる。
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/api/analytics/pending", methods=["GET"])
def api_analytics_pending_status():
    """`data/analytics_pending.jsonl` に残っている件数 + 最古エントリの時刻。"""
    from analytics import pending_queue
    entries = pending_queue.read_all()
    if not entries:
        return jsonify({"count": 0, "oldest_at": None})
    oldest = min(
        (e.get("timestamp") for e in entries if e.get("timestamp")),
        default=None,
    )
    return jsonify({
        "count": len(entries),
        "oldest_at": oldest,
        "platforms": sorted({
            e.get("platform") for e in entries if e.get("platform")
        }),
    })


@analytics_bp.route("/api/analytics/pending/sync", methods=["POST"])
def api_analytics_pending_sync():
    """queue を replay して、成功した ts は publish stage を generated にマーク。"""
    from analytics import pending_queue
    from final_import.publish import finalize_pending_publish

    result = pending_queue.replay()
    finalized: list[str] = []
    for ts in result.get("synced_ts") or []:
        try:
            if finalize_pending_publish(ts):
                finalized.append(ts)
        except Exception as e:
            logger.warning(
                "[pending-sync] finalize_pending_publish(%s) 失敗: %s", ts, e,
            )
    return jsonify({
        "success": result.get("success", 0),
        "failed": result.get("failed", 0),
        "synced_ts": result.get("synced_ts") or [],
        "finalized_ts": finalized,
    })
