"""routes/analyze.py — analyze job 関連 endpoint。

preview_server.py から段階移行 (= 計画書 §3.1.2-b):

- GET    /api/screenplay/analyze/<job_id>          : job 詳細 + phases
- POST   /api/screenplay/analyze/<job_id>/confirm  : awaiting_confirm → running
- GET    /api/screenplay/analyze/<job_id>/events   : SSE event stream
- DELETE /api/screenplay/analyze/<job_id>          : ジョブをキャンセル
"""

from __future__ import annotations

import json
import logging
import re

from flask import Blueprint, Response, jsonify

from analyze import job as analyze_job
from analyze import progress as analyze_progress
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


@analyze_bp.route("/api/screenplay/analyze/<job_id>/events", methods=["GET"])
def api_analyze_job_events(job_id):
    """SSE で event をストリーミング配信する。"""
    if not _JOB_ID_RE.match(job_id):
        return api_error("ANALYZE_INVALID_JOB_ID", "invalid job_id", 400)
    try:
        snapshot = _job_to_dict(analyze_job.get_job(job_id))
    except KeyError:
        return api_error("ANALYZE_JOB_NOT_FOUND", "job not found", 404)

    terminal_events = ("completed", "failed", "cancelled")
    is_terminal = snapshot["status"] in terminal_events
    # 既に終端状態でなければ、state event を yield する**前に** subscribe して
    # queue を確保する (state yield 中に publish された event を取りこぼさない)。
    sub_iter = None if is_terminal else analyze_progress.subscribe(job_id)

    def gen():
        try:
            yield (
                "event: state\n"
                f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            )
            if is_terminal:
                return
            for event, data in sub_iter:
                payload = json.dumps(data, ensure_ascii=False, default=str)
                yield f"event: {event}\ndata: {payload}\n\n"
                if event in terminal_events:
                    break
        finally:
            if sub_iter is not None:
                sub_iter.close()

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@analyze_bp.route("/api/screenplay/analyze/<job_id>", methods=["DELETE"])
def api_cancel_analyze_job(job_id):
    """ジョブのキャンセルを要求 (各フェーズ境界で読まれて中断)。"""
    if not _JOB_ID_RE.match(job_id):
        return api_error("ANALYZE_INVALID_JOB_ID", "invalid job_id", 400)
    try:
        analyze_job.get_job(job_id)
    except KeyError:
        return api_error("ANALYZE_JOB_NOT_FOUND", "job not found", 404)
    analyze_runner.cancel(job_id)
    return jsonify({"ok": True}), 202
