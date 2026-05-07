from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(config.BASE_DIR) / "data" / "analytics_pending.jsonl"
_WRITE_LOCK = threading.Lock()


def _path() -> Path:
    return Path(os.environ.get("ANALYTICS_PENDING_PATH", str(_DEFAULT_PATH)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(entry: dict[str, Any]) -> None:
    payload = dict(entry)
    payload.setdefault("timestamp", _now_iso())
    line = json.dumps(payload, ensure_ascii=False)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def read_all() -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning("analytics_pending.jsonl 不正行をスキップ: %s", e)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return out


def rewrite(entries: list[dict[str, Any]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with _WRITE_LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                for e in entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.replace(tmp, path)


def replay() -> dict[str, Any]:
    """queue を消費して analytics DB に再登録する。

    成功した entry は queue から削除、失敗は残す。caller (= preview_server 起動時
    auto-replay や ``scripts/sync_pending_analytics.py``) は戻り値の
    ``synced_ts`` を見て、対応する project の Stage 8 を ``mark_generated`` に
    昇格させる (= ``final_import.publish.finalize_pending_publish``)。

    Returns: {"success": int, "failed": int, "synced_ts": list[str]}
    """
    entries = read_all()
    if not entries:
        return {"success": 0, "failed": 0, "synced_ts": []}

    from analytics import db as analytics_db  # 遅延 import で循環回避

    analytics_db.init_db()
    remaining: list[dict[str, Any]] = []
    success = 0
    failed = 0
    synced_ts: list[str] = []
    for entry in entries:
        try:
            analytics_db.register_post(
                video_id=entry["ts"],
                platform=entry["platform"],
                platform_post_id=entry["platform_post_id"],
                url=entry.get("url"),
                posted_at=entry.get("posted_at"),
                caption=entry.get("caption"),
                hashtags=entry.get("hashtags"),
            )
            success += 1
            synced_ts.append(entry["ts"])
            logger.info(
                "[analytics-replay] 同期成功: %s:%s",
                entry["platform"], entry["platform_post_id"],
            )
        except Exception as e:
            failed += 1
            remaining.append(entry)
            logger.error(
                "[analytics-replay] 同期失敗 (queue に残します): %s:%s — %s",
                entry.get("platform"),
                entry.get("platform_post_id"), e,
            )

    rewrite(remaining)
    return {"success": success, "failed": failed, "synced_ts": synced_ts}
