"""Stage 7 (final import) + Stage 8 (publish) の Blueprint。

`preview_server.py` から段階移行 (= cost / analytics / config / projects /
stages に続く 6 番目)。final-version 管理 + publish 起動 + 履歴取得を 1 module
にまとめる。
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict

from flask import Blueprint, abort, jsonify, request, send_file

import staged_pipeline
from job_runner import (
    JobAlreadyRunningError,
    job_already_running_response,
    spawn_job,
)

from routes._helpers import ts_path, validate_ts

logger = logging.getLogger(__name__)

final_publish_bp = Blueprint("final_publish", __name__)

_FILENAME_RE = re.compile(r"^[\w\.\-]+$")


# ───────────────── Stage 7 final import ─────────────────

@final_publish_bp.route("/api/projects/<ts>/final", methods=["GET"])
def api_list_finals(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    from final_import import core as fi
    versions = [asdict(v) for v in fi.list_final_versions(project_path)]
    return jsonify({"final_versions": versions})


@final_publish_bp.route(
    "/api/projects/<ts>/final/<filename>/canonical", methods=["POST"],
)
def api_set_canonical_final(ts, filename):
    validate_ts(ts)
    if not _FILENAME_RE.match(filename):
        return jsonify({"error": "invalid filename"}), 400
    from final_import import core as fi
    try:
        v = fi.set_canonical_final(ts_path(ts), filename)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"final_version": asdict(v)})


@final_publish_bp.route(
    "/api/projects/<ts>/final/<filename>", methods=["DELETE"],
)
def api_delete_final(ts, filename):
    validate_ts(ts)
    if not _FILENAME_RE.match(filename):
        return jsonify({"error": "invalid filename"}), 400
    from final_import import core as fi
    try:
        fi.delete_final_version(ts_path(ts), filename)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"ok": True, "deleted": filename})


@final_publish_bp.route("/asset/<ts>/final-version/<filename>")
def asset_final_version(ts, filename):
    validate_ts(ts)
    if not _FILENAME_RE.match(filename):
        abort(400)
    from final_import import core as fi
    p = fi.final_dir(ts_path(ts)) / filename
    if not p.exists():
        return "", 404
    return send_file(str(p), mimetype="video/mp4", conditional=True)


# ───────────────── Stage 8 publish ─────────────────

@final_publish_bp.route("/api/projects/<ts>/publish", methods=["POST"])
def api_publish(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    data = request.get_json(force=True) or {}
    platform = data.get("platform")
    if platform not in ("youtube", "instagram", "tiktok"):
        return jsonify({"error": f"invalid platform: {platform}"}), 400
    privacy = data.get("privacy", "private")
    if privacy not in ("private", "unlisted", "public"):
        return jsonify({"error": f"invalid privacy: {privacy}"}), 400

    def _do_publish():
        from final_import.publish import publish
        return publish(ts, platform, privacy=privacy)

    try:
        job_id = spawn_job(_do_publish, kind=f"publish-{platform}", ts=ts)
    except JobAlreadyRunningError as e:
        return job_already_running_response(e)
    return jsonify({"job_id": job_id})


@final_publish_bp.route("/api/projects/<ts>/publish-history", methods=["GET"])
def api_publish_history(ts):
    validate_ts(ts)
    meta = staged_pipeline.read_metadata(ts_path(ts)) or {}
    return jsonify({"published_posts": meta.get("published_posts") or []})
