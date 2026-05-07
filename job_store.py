"""バックグラウンドジョブ (run-next / regen / publish 等) の永続化。

preview_server の `_jobs` dict はメモリ上のみで、サーバ再起動すると
in-flight だったジョブのステータスが消える (= UI からは「消失」状態)。
このモジュールは job state を ``data/jobs.json`` に書き出し、起動時に
"running" のままになっていたエントリを "lost" に書き換えて UI に
明示する。

ジョブ自体 (= バックグラウンド thread) はプロセス再起動を跨いで再開
できないので、disk 上の生成物 + progress_store でユーザに再実行を
促す前提。
"""

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

JOBS_FILENAME = "jobs.json"
DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data",
)
MAX_HISTORY = 500


_lock = threading.Lock()


def _data_dir() -> str:
    return os.environ.get("JOB_STORE_DIR") or DEFAULT_DATA_DIR


def _path() -> str:
    return os.path.join(_data_dir(), JOBS_FILENAME)


def _load() -> dict:
    p = _path()
    if not os.path.exists(p):
        return {"jobs": {}}
    try:
        with open(p) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"jobs": {}}
    if not isinstance(data, dict) or "jobs" not in data:
        return {"jobs": {}}
    return data


def _save(data: dict) -> None:
    os.makedirs(_data_dir(), exist_ok=True)
    p = _path()
    tmp = p + ".tmp"
    raw = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError as e:
            logger.warning("[job-store] tmp %s 削除失敗: %s", tmp, e)
        raise


def _trim_history(data: dict) -> None:
    """エントリ数が MAX_HISTORY を超えたら古い completed / failed / lost を削除。

    "running" エントリは絶対に消さない (= 監視中のジョブなので)。
    """
    jobs = data.get("jobs") or {}
    if len(jobs) <= MAX_HISTORY:
        return
    closable = [
        (jid, j) for jid, j in jobs.items()
        if j.get("status") in ("completed", "failed", "lost")
    ]
    closable.sort(key=lambda kv: kv[1].get("finished_at") or "")
    to_remove = len(jobs) - MAX_HISTORY
    for jid, _ in closable[:to_remove]:
        jobs.pop(jid, None)


def create(job_id: str, *, kind: str, ts: str,
           started_at: float | None = None) -> dict:
    started = started_at if started_at is not None else time.time()
    rec = {
        "id": job_id,
        "kind": kind,
        "ts": ts,
        "status": "running",
        "started_at": started,
        "finished_at": None,
        "error": None,
    }
    with _lock:
        data = _load()
        data["jobs"][job_id] = rec
        _trim_history(data)
        _save(data)
    return rec


def update(job_id: str, **fields: Any) -> dict | None:
    with _lock:
        data = _load()
        rec = data["jobs"].get(job_id)
        if rec is None:
            return None
        for k, v in fields.items():
            rec[k] = v
        if fields.get("status") in ("completed", "failed", "lost") and \
                rec.get("finished_at") is None:
            rec["finished_at"] = time.time()
        _save(data)
        return rec


def get(job_id: str) -> dict | None:
    with _lock:
        return _load()["jobs"].get(job_id)


def list_all() -> list[dict]:
    with _lock:
        jobs = list(_load()["jobs"].values())
    jobs.sort(key=lambda j: j.get("started_at") or 0, reverse=True)
    return jobs


def recover_lost() -> list[dict]:
    """サーバ起動時に呼ぶ: status="running" のエントリを "lost" に書換える。

    Returns:
        書換えた job のリスト (= dict with id, ts, kind, ...)。caller は ts を
        使って partial artifact のクリーンアップに使う。
    """
    affected: list[dict] = []
    with _lock:
        data = _load()
        now = time.time()
        for jid, rec in (data.get("jobs") or {}).items():
            if rec.get("status") == "running":
                rec["status"] = "lost"
                rec["finished_at"] = now
                rec["error"] = (
                    "preview_server 再起動時に running のままだったため lost "
                    "扱い (生成物が disk に残っていれば run-next で再開可能)"
                )
                affected.append(dict(rec))
        if affected:
            _save(data)
    return affected
