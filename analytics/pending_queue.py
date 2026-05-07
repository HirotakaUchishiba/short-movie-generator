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
