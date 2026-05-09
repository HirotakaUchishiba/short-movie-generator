"""バックグラウンドジョブの spawn / 状態追跡 / 排他制御。

`preview_server.py` から段階移行で抽出した module。共有 state (= `_jobs` /
`_jobs_lock` / `_active_ts`) を 1 module に集約し、Blueprint 化された routes
(= 将来の routes/stages.py / routes/publish.py 等) からも安全に呼べる
ようにする。

主要 API:
- ``spawn_job(fn, *, kind, ts, exclusive_ts=True) -> job_id`` で daemon
  スレッドを起動し、状態を _jobs に積む。
- ``JobAlreadyRunningError`` は同 ts に running job がある時に raise。
- ``job_already_running_response(e)`` は HTTP 409 用 JSON を返す。
- ``get_job(job_id)`` でメモリ + disk fallback。
- ``recover_lost_jobs()`` は server 起動時に呼ばれ、orphan running job を
  ``status=lost`` に降格。
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable

from flask import jsonify

import job_store

logger = logging.getLogger(__name__)


_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
# ts → 現在実行中の job_id。``spawn_job(exclusive_ts=True)`` で同 ts への
# 並行 spawn を防ぐ。runner 終了時に _jobs_lock 配下で削除する。
_active_ts: dict[str, str] = {}


class JobAlreadyRunningError(RuntimeError):
    """同一 ts に対して既に running の job がある時に raise される。"""

    def __init__(self, ts: str, existing_job_id: str, existing_kind: str):
        super().__init__(
            f"ts={ts} には既に実行中の job があります "
            f"(job_id={existing_job_id}, kind={existing_kind})"
        )
        self.ts = ts
        self.existing_job_id = existing_job_id
        self.existing_kind = existing_kind


def spawn_job(fn: Callable[[], Any], *, kind: str, ts: str,
              exclusive_ts: bool = True) -> str:
    """job runner を spawn する。

    exclusive_ts=True (= 既定) のとき、同じ ts に対して既に running の job が
    あれば JobAlreadyRunningError を raise する。caller は HTTP 409 を返す。
    並行起動禁止対象は stage runner / regen / cache fresh / publish。read-only
    job (= 過去ログ取得など) はそもそも spawn_job を使わないので影響なし。
    """
    job_id = str(uuid.uuid4())[:8]
    started_at = time.time()
    with _jobs_lock:
        if exclusive_ts:
            existing_id = _active_ts.get(ts)
            if existing_id and existing_id in _jobs:
                existing = _jobs[existing_id]
                if existing.get("status") == "running":
                    raise JobAlreadyRunningError(
                        ts, existing_id, existing.get("kind") or "?",
                    )
        _jobs[job_id] = {
            "id": job_id, "kind": kind, "ts": ts,
            "status": "running", "log": [], "started_at": started_at,
            "error": None,
        }
        if exclusive_ts:
            _active_ts[ts] = job_id
    job_store.create(job_id, kind=kind, ts=ts, started_at=started_at)

    def runner():
        try:
            fn()
            with _jobs_lock:
                _jobs[job_id]["status"] = "completed"
                if _active_ts.get(ts) == job_id:
                    _active_ts.pop(ts, None)
            job_store.update(job_id, status="completed")
        except Exception as e:
            logger.exception("job %s failed", job_id)
            with _jobs_lock:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = str(e)
                if _active_ts.get(ts) == job_id:
                    _active_ts.pop(ts, None)
            job_store.update(job_id, status="failed", error=str(e))
    threading.Thread(target=runner, daemon=True).start()
    return job_id


def job_already_running_response(e: JobAlreadyRunningError):
    """409 用 JSON tuple。caller の Flask handler でそのまま return できる。"""
    return jsonify({
        "error": str(e),
        "ts": e.ts,
        "existing_job_id": e.existing_job_id,
        "existing_kind": e.existing_kind,
    }), 409


def get_job(job_id: str) -> dict | None:
    """メモリから取得 (= 不在なら disk job_store から fallback)。"""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is not None:
        return dict(job)
    persisted = job_store.get(job_id)
    return persisted or None


def get_jobs_view() -> dict[str, dict]:
    """テスト / introspection 用。``_jobs`` の shallow copy を返す。"""
    with _jobs_lock:
        return {k: dict(v) for k, v in _jobs.items()}
