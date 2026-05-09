"""Stage 7 (final import) + Stage 8 (publish) の Blueprint。

`preview_server.py` から段階移行 (= cost / analytics / config / projects /
stages に続く 6 番目)。final-version 管理 + publish 起動 + 履歴取得を 1 module
にまとめる。
"""
from __future__ import annotations

import logging
import os
import re
import uuid
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


@final_publish_bp.route("/api/projects/<ts>/final", methods=["POST"])
def api_upload_final(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file required (multipart 'file' field)"}), 400
    skip_fp = request.args.get("no_fingerprint", "").lower() in ("1", "true", "yes")

    from final_import import core as fi
    fi.ensure_final_dir(project_path)
    name = os.path.basename(f.filename or "upload.mp4")
    ext = os.path.splitext(name)[1].lower()
    if ext not in fi.ALLOWED_EXTS:
        return jsonify({"error": f"unsupported extension: {ext}"}), 400

    # 一旦 ts_path 直下の中間 staging に置く (final_d の外なので import_final が
    # ちゃんと HHMMSS.mp4 にリネームコピーする)。
    staging_dir = os.path.join(project_path, ".final_upload")
    os.makedirs(staging_dir, exist_ok=True)
    tmp = os.path.join(staging_dir, f"upload_{uuid.uuid4().hex}{ext}")
    try:
        f.save(tmp)
        v = fi.import_final(ts, tmp, source="ui", skip_fingerprint=skip_fp)
        return jsonify({"final_version": asdict(v)}), 201
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 400
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError as e:
            logger.warning("[final-upload] tmp %s unlink 失敗: %s", tmp, e)


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
    channel = (data.get("channel") or "").strip() or None

    def _do_publish():
        from final_import.publish import publish
        return publish(ts, platform, privacy=privacy, profile=channel)

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


# ───────────────── YouTube channel info ─────────────────

@final_publish_bp.route("/api/youtube/profiles", methods=["GET"])
def api_youtube_profiles():
    """``.env`` 内に存在する YOUTUBE_PROFILE 候補を列挙する。

    ``YOUTUBE_OAUTH_CLIENT_ID_<NAME>`` 形式の env を scan して ``<NAME>`` を返す。
    suffix なし env が揃っていれば ``"default"`` も先頭に含める。UI の selector
    が「現在の .env でどの profile が選択可能か」を判断するのに使う。
    """
    profiles: list[str] = []
    if all(os.environ.get(k) for k in (
        "YOUTUBE_OAUTH_CLIENT_ID",
        "YOUTUBE_OAUTH_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
    )):
        profiles.append("default")

    for k in os.environ:
        if not k.startswith("YOUTUBE_OAUTH_CLIENT_ID_"):
            continue
        name = k[len("YOUTUBE_OAUTH_CLIENT_ID_"):]
        if not name or name in profiles:
            continue
        # client_secret と refresh_token も揃っていなければ「使える profile」ではない
        if not os.environ.get(f"YOUTUBE_OAUTH_CLIENT_SECRET_{name}"):
            continue
        if not os.environ.get(f"YOUTUBE_REFRESH_TOKEN_{name}"):
            continue
        profiles.append(name)
    return jsonify({"profiles": profiles})


@final_publish_bp.route("/api/youtube/channel-info", methods=["GET"])
def api_youtube_channel_info():
    """指定 profile での投稿先 channel info を返す (= UI の事前表示用)。

    ``profile`` クエリパラメータが指定されていれば一時的に env を override し、
    ``_resolve_channel_label`` で profile / aud / scopes / title / channel_id /
    error を取得して返す。
    """
    from final_import.publish import _profile_context
    from platform_clients import youtube

    profile = (request.args.get("profile") or "").strip() or None
    with _profile_context(profile):
        info = youtube._resolve_channel_label()
    return jsonify(info)
