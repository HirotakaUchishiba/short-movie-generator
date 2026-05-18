"""``/api/reference_videos*`` の Blueprint (= analyze 用素材 CRUD)。

preview_server.py から段階移行 (= cost / analytics / config / projects /
stages / final_publish / assets / intent_* に続く)。

multipart upload は ``routes._helpers.save_reference_video`` 経由で
content-addressed (sha256) に dedup される。GET は一覧、DELETE は
``?force=true`` で関連 analyze ジョブごと削除する。
"""
from __future__ import annotations

import os
import re

from flask import Blueprint, jsonify, request

from analyze import job as analyze_job

from routes._helpers import api_error, save_reference_video

reference_videos_bp = Blueprint("reference_videos", __name__)

_SHA256_RE = re.compile(r'^[a-f0-9]{64}$')


@reference_videos_bp.route("/api/reference_videos", methods=["POST"])
def api_upload_reference_video():
    """multipart で動画をアップロードし、content-addressed (sha256) で保存する。

    既存 sha256 と一致する場合は dedup され既存メタを返す (HTTP 200)。
    新規なら 201。実体は ``routes._helpers.save_reference_video`` を経由
    (= POST /api/projects/from-reference-video と共通経路)。
    """
    f = request.files.get("file")
    if not f:
        return api_error(
            "REFERENCE_VIDEO_FILE_REQUIRED",
            "file required (multipart 'file' field)",
            400,
        )
    try:
        result = save_reference_video(f)
    except ValueError as e:
        return api_error(
            "REFERENCE_VIDEO_UNSUPPORTED_EXT", str(e), 400,
            allowed=list(analyze_job.ALLOWED_VIDEO_EXTS),
        )
    status = 200 if result["deduplicated"] else 201
    return jsonify(result), status


@reference_videos_bp.route("/api/reference_videos", methods=["GET"])
def api_list_reference_videos():
    return jsonify({"reference_videos": analyze_job.list_reference_videos()})


@reference_videos_bp.route("/api/reference_videos/<sha>", methods=["DELETE"])
def api_delete_reference_video(sha):
    if not _SHA256_RE.match(sha):
        return api_error(
            "REFERENCE_VIDEO_INVALID_SHA256",
            "invalid sha256 (64 hex chars required)",
            400,
        )

    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    deleted = analyze_job.delete_reference_video(sha, force=force)
    if not deleted:
        n = analyze_job.count_jobs_for_video(sha)
        return api_error(
            "REFERENCE_VIDEO_REFERENCED_BY_JOBS",
            (
                f"この動画は {n} 件の analyze ジョブから参照されています。"
                "?force=true を指定すると関連ジョブごと削除します。"
            ),
            409,
            count=n,
            # 旧 frontend が job_count を読んでいるので併記 (= 段階的移行)
            job_count=n,
        )

    file_path = analyze_job.reference_video_path(sha)
    if file_path and os.path.exists(file_path):
        os.unlink(file_path)
        return jsonify({"sha256": sha, "deleted": True, "force": force}), 200
    return jsonify({
        "sha256": sha, "deleted": True, "force": force,
        "warning": "DB row deleted but file not found",
    }), 200
