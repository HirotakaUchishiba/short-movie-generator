"""24h 自律稼働用の参考動画 URL キュー (= auto_loop の入力供給)。

`data/url_queue.jsonl` に 1 行 1 ジョブで永続化する。autonomous_runner が
`next_pending` → `run_one_video` → `mark` で消化する。書き込みは temp + replace で
atomic (= 途中クラッシュで JSONL を壊さない)。

単一ランナー前提 (= 並行ロックは持たない)。複数ランナーは将来。
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import config

VALID_STATUSES = ("pending", "done", "failed")


def _queue_path() -> str:
    return os.path.join(config.BASE_DIR, "data", "url_queue.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_all(path: str | None = None) -> list[dict]:
    path = path or _queue_path()
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _write_all(jobs: list[dict], path: str | None = None) -> None:
    path = path or _queue_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for j in jobs:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def enqueue(url: str, license_status: str, path: str | None = None) -> str:
    """ジョブを追加して id を返す。"""
    jobs = _read_all(path)
    job_id = uuid.uuid4().hex[:12]
    jobs.append({
        "id": job_id,
        "url": url,
        "license": license_status,
        "status": "pending",
        "ts": None,
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    _write_all(jobs, path)
    return job_id


def next_pending(path: str | None = None) -> dict | None:
    """先頭の pending ジョブを返す (= FIFO)。無ければ None。"""
    for j in _read_all(path):
        if j.get("status") == "pending":
            return j
    return None


def mark(job_id: str, status: str, *, ts: str | None = None,
         error: str | None = None, path: str | None = None) -> bool:
    """ジョブの status を更新する。見つかれば True。"""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r} (valid: {VALID_STATUSES})")
    jobs = _read_all(path)
    found = False
    for j in jobs:
        if j.get("id") == job_id:
            j["status"] = status
            if ts is not None:
                j["ts"] = ts
            if error is not None:
                j["error"] = error
            j["updated_at"] = _now()
            found = True
            break
    if found:
        _write_all(jobs, path)
    return found


def list_jobs(status: str | None = None,
              path: str | None = None) -> list[dict]:
    jobs = _read_all(path)
    if status:
        return [j for j in jobs if j.get("status") == status]
    return jobs
