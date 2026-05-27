"""コード開発の自律ループ用タスクバックログ。

24h 開発体制で /goal + superpowers 手法 (brainstorm→plan→TDD→review→finish) が
消化する「次に何を作る / 直すか」を永続管理する。`data/dev_backlog.jsonl` に 1 行 1
タスク。優先度 (priority 小さいほど先) → 作成順 で next_pending が返す。

動画生成の URL キュー (`autonomous/task_queue.py`) とは別物 (= タスクは title/detail/
priority を持つ)。書き込みは temp + replace で atomic。
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import config

VALID_STATUSES = ("pending", "in_progress", "done", "failed")


def _path() -> str:
    return os.path.join(config.BASE_DIR, "data", "dev_backlog.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_all(path: str | None = None) -> list[dict]:
    path = path or _path()
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


def _write_all(tasks: list[dict], path: str | None = None) -> None:
    path = path or _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def add(title: str, detail: str = "", priority: int = 3,
        path: str | None = None) -> str:
    """開発タスクを追加して id を返す。priority は小さいほど優先。"""
    tasks = _read_all(path)
    tid = uuid.uuid4().hex[:12]
    tasks.append({
        "id": tid,
        "title": title,
        "detail": detail,
        "priority": int(priority),
        "status": "pending",
        "branch": None,
        "pr": None,
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    _write_all(tasks, path)
    return tid


def next_pending(path: str | None = None) -> dict | None:
    """最優先の pending タスクを返す (priority 昇順 → created_at 昇順)。"""
    pend = [t for t in _read_all(path) if t.get("status") == "pending"]
    if not pend:
        return None
    pend.sort(key=lambda t: (t.get("priority", 3), t.get("created_at", "")))
    return pend[0]


def mark(task_id: str, status: str, *, branch: str | None = None,
         pr: str | None = None, error: str | None = None,
         path: str | None = None) -> bool:
    """タスクの status を更新する。branch/pr/error も任意で記録。"""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r} (valid: {VALID_STATUSES})")
    tasks = _read_all(path)
    found = False
    for t in tasks:
        if t.get("id") == task_id:
            t["status"] = status
            if branch is not None:
                t["branch"] = branch
            if pr is not None:
                t["pr"] = pr
            if error is not None:
                t["error"] = error
            t["updated_at"] = _now()
            found = True
            break
    if found:
        _write_all(tasks, path)
    return found


def list_tasks(status: str | None = None,
               path: str | None = None) -> list[dict]:
    tasks = _read_all(path)
    if status:
        return [t for t in tasks if t.get("status") == status]
    return tasks
