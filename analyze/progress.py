"""analyze ジョブの SSE event publisher / subscriber。

ジョブ runner thread が publish() で event を発信し、
SSE エンドポイントが subscribe() ジェネレータで受信する。
複数 subscriber 対応 (同じ job_id を複数のクライアントが同時購読可能)。
"""
import logging
import queue
import threading
import time
from typing import Iterator

logger = logging.getLogger(__name__)

# heartbeat 間隔 (proxy / load balancer 経由でも接続を生かす)
HEARTBEAT_SEC = 25.0

# subscriber キューのサイズ上限 (溢れた場合は drop)
QUEUE_MAXSIZE = 200

_SUBSCRIBERS: dict[str, list[queue.Queue]] = {}
_LOCK = threading.Lock()


def publish(job_id: str, event: str, data: dict) -> None:
    """全 subscriber に (event, data) を push。

    subscriber が遅すぎる場合は drop し、警告ログを出す。
    """
    with _LOCK:
        qs = list(_SUBSCRIBERS.get(job_id, []))
    for q in qs:
        try:
            q.put_nowait((event, data))
        except queue.Full:
            logger.warning(
                "subscriber queue full for job %s, dropping %s", job_id, event,
            )


def subscribe(job_id: str, *,
               heartbeat_sec: float = HEARTBEAT_SEC,
               ) -> Iterator[tuple[str, dict]]:
    """SSE 用イベント受信ジェネレータを返す。

    重要: queue 登録は subscribe() を呼び出した時点で同期的に行われる
    (返り値のジェネレータを iterate するまで遅延しない)。これにより、
    subscribe 直後に publish された event が drop されない。
    """
    q: queue.Queue = queue.Queue(maxsize=QUEUE_MAXSIZE)
    with _LOCK:
        _SUBSCRIBERS.setdefault(job_id, []).append(q)
    return _stream_events(job_id, q, heartbeat_sec)


def _stream_events(job_id: str, q: queue.Queue,
                    heartbeat_sec: float) -> Iterator[tuple[str, dict]]:
    try:
        while True:
            try:
                yield q.get(timeout=heartbeat_sec)
            except queue.Empty:
                yield ("heartbeat", {"ts": time.time()})
    finally:
        with _LOCK:
            if job_id in _SUBSCRIBERS:
                _SUBSCRIBERS[job_id] = [
                    x for x in _SUBSCRIBERS[job_id] if x is not q
                ]
                if not _SUBSCRIBERS[job_id]:
                    del _SUBSCRIBERS[job_id]


def subscriber_count(job_id: str) -> int:
    with _LOCK:
        return len(_SUBSCRIBERS.get(job_id, []))


def clear_subscribers(job_id: str | None = None) -> None:
    """テスト用: 特定 job_id (or 全部) の subscriber を解除する。"""
    with _LOCK:
        if job_id is None:
            _SUBSCRIBERS.clear()
        else:
            _SUBSCRIBERS.pop(job_id, None)
