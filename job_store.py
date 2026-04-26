import json
import logging
import os
import threading
from typing import Any

import config

logger = logging.getLogger(__name__)

_SERIALIZABLE_KEYS = {
    "id", "status", "timestamp", "screenplay_name", "backed_up", "edits",
    "cost_estimate", "prompts_before", "prompts_after", "log", "started_at",
    "pid",
}


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        os.makedirs(config.JOBS_DIR, exist_ok=True)
        self._load_all()

    def _job_path(self, job_id: str) -> str:
        return os.path.join(config.JOBS_DIR, f"{job_id}.json")

    def _serialize(self, job: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in job.items() if k in _SERIALIZABLE_KEYS}

    def _load_all(self) -> None:
        if not os.path.isdir(config.JOBS_DIR):
            return
        for fname in os.listdir(config.JOBS_DIR):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(config.JOBS_DIR, fname)
            try:
                with open(path) as f:
                    data = json.load(f)
                job_id = data.get("id")
                if not job_id:
                    continue
                if data.get("status") == "running":
                    data["status"] = "failed"
                    data.setdefault("log", []).append(
                        "\n--- サーバ再起動のため中断 ---"
                    )
                self._jobs[job_id] = data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("ジョブ読込失敗 %s: %s", fname, exc)

    def _persist(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        try:
            with open(self._job_path(job_id), "w") as f:
                json.dump(self._serialize(job), f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("ジョブ書き込み失敗 %s: %s", job_id, exc)

    def create(self, job_id: str, initial: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job_id] = initial
            self._persist(job_id)

    def update(self, job_id: str, mutator) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            mutator(job)
            self._persist(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._jobs.values())

    def cleanup(self, max_jobs: int) -> None:
        with self._lock:
            if len(self._jobs) <= max_jobs:
                return
            completed = sorted(
                (j for j in self._jobs.values()
                 if j["status"] in ("completed", "failed")),
                key=lambda j: j["started_at"],
            )
            to_remove = len(self._jobs) - max_jobs
            for job in completed[:to_remove]:
                job_id = job["id"]
                self._jobs.pop(job_id, None)
                try:
                    os.remove(self._job_path(job_id))
                except OSError:
                    pass
