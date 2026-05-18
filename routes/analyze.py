"""routes/analyze.py — analyze job 関連 endpoint。

preview_server.py から段階移行 (= 計画書 §3.1.2-b):

- GET  /api/screenplay/analyze/<job_id>          : job 詳細 + phases
- POST /api/screenplay/analyze/<job_id>/confirm  : awaiting_confirm → running

events (= SSE) / cancel (= DELETE) は将来 PR で同パターン移行する
(= state 共有がある job_runner / analyze_progress の取扱に注意)。
"""

from __future__ import annotations

import json
import logging
import re

from flask import Blueprint, jsonify

from analyze import job as analyze_job
from analyze import runner as analyze_runner
from routes._helpers import api_error

logger = logging.getLogger(__name__)

analyze_bp = Blueprint("analyze", __name__)

# job_id format: "analyze_<sha>". preview_server 側の同名 regex と一致させる
# (= 両方 active で並走する間の挙動互換性を保つ)。
_JOB_ID_RE = re.compile(r"^analyze_[\w]+$")


def _job_to_dict(j) -> dict:
    """analyze_job.Job → dict 変換 (= preview_server._job_to_dict と同一)。"""
    return {
        "id": j.id,
        "video_sha256": j.video_sha256,
        "options": json.loads(j.options_json),
        "status": j.status,
        "current_phase": j.current_phase,
        "error": j.error,
        "estimated_cost_usd": j.estimated_cost_usd,
        "actual_cost_usd": j.actual_cost_usd,
        "screenplay_path": j.screenplay_path,
        "style_name": j.style_name,
        "created_at": j.created_at,
        "started_at": j.started_at,
        "finished_at": j.finished_at,
        "cancellation_requested": bool(j.cancellation_requested),
    }


@analyze_bp.route("/api/screenplay/analyze/<job_id>", methods=["GET"])
def api_analyze_job_detail(job_id):
    if not _JOB_ID_RE.match(job_id):
        return api_error("ANALYZE_INVALID_JOB_ID", "invalid job_id", 400)
    try:
        j = analyze_job.get_job(job_id)
    except KeyError:
        return api_error("ANALYZE_JOB_NOT_FOUND", "job not found", 404)
    phases = analyze_job.get_phases(job_id)
    return jsonify({**_job_to_dict(j), "phases": phases})


@analyze_bp.route(
    "/api/screenplay/analyze/<job_id>/confirm", methods=["POST"],
)
def api_confirm_analyze_job(job_id):
    """awaiting_confirm 状態のジョブを running に遷移させて Claude 続行。"""
    if not _JOB_ID_RE.match(job_id):
        return api_error("ANALYZE_INVALID_JOB_ID", "invalid job_id", 400)
    try:
        analyze_runner.confirm(job_id)
    except KeyError:
        return api_error("ANALYZE_JOB_NOT_FOUND", "job not found", 404)
    except ValueError as e:
        # ValueError は「既に running / 既に terminal」等の状態遷移エラー
        # (= dryrun 二重クリックのケース) で 409 を返す
        return api_error("ANALYZE_JOB_INVALID_STATE", str(e), 409)
    return jsonify({"ok": True}), 200
