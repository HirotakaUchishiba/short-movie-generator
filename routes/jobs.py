"""``/api/jobs/<job_id>`` の Blueprint (= job 進捗ステータス参照)。

preview_server.py から段階移行 (= §3.1.2)。実体は ``job_runner.get_job``
が memory + disk fallback を統合してくれているので Blueprint は薄い。
"""
from __future__ import annotations

import time

from flask import Blueprint, jsonify

import job_runner

from routes._helpers import api_error

jobs_bp = Blueprint("jobs", __name__)


@jobs_bp.route("/api/jobs/<job_id>", methods=["GET"])
def api_job(job_id):
    """job_id の現在 status を返す (= memory → disk の順で lookup)。"""
    job = job_runner.get_job(job_id)
    if not job:
        return api_error(
            "JOB_NOT_FOUND", "ジョブが見つかりません", 404, job_id=job_id,
        )
    started = job.get("started_at") or time.time()
    finished = job.get("finished_at")
    elapsed = round((finished or time.time()) - started, 1)
    return jsonify({
        "id": job["id"],
        "kind": job["kind"],
        "ts": job["ts"],
        "status": job["status"],
        "elapsed": elapsed,
        "error": job.get("error"),
    })
