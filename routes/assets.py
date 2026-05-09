"""``/asset/*`` 配信の Blueprint (= TTS / BG / Kling / scene / overlay /
character / reference-video / location preview)。

`preview_server.py` から段階移行 (= cost / analytics / config / projects /
stages / final_publish に続く 7 番目)。フロントの `<video src=...>` /
`<img src=...>` から大量に呼ばれる read-only 配信を 1 module にまとめる。
"""
from __future__ import annotations

import logging
import os
import re

from flask import Blueprint, abort, jsonify, send_file

import scene_gen
from analyze import job as analyze_job

from routes._helpers import (
    load_screenplay_for_project,
    safe_join,
    ts_path,
    validate_ts,
)

logger = logging.getLogger(__name__)

assets_bp = Blueprint("assets", __name__)

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_NAME_RE = re.compile(r"^[\w\-]+$")


@assets_bp.route("/asset/<ts>/tts/<int:scene_idx>/<int:line_idx>")
def asset_tts(ts, scene_idx, line_idx):
    validate_ts(ts)
    base = ts_path(ts)
    adj = safe_join(base, f"tts_{scene_idx:03d}_{line_idx:03d}.adj.mp3")
    raw = safe_join(base, f"tts_{scene_idx:03d}_{line_idx:03d}.mp3")
    if os.path.exists(adj):
        return send_file(adj, mimetype="audio/mpeg")
    if os.path.exists(raw):
        return send_file(raw, mimetype="audio/mpeg")
    return "", 404


@assets_bp.route("/asset/<ts>/tts-merged")
def asset_tts_merged(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return "", 404
    sp, _name = load_screenplay_for_project(ts)
    try:
        path = scene_gen.build_merged_tts_preview(sp, project_path)
    except Exception as e:
        logger.exception("merged TTS build failed")
        return jsonify({"error": str(e)}), 500
    if not path or not os.path.exists(path):
        return "", 404
    mimetype = "audio/mp4" if path.endswith(".m4a") else "audio/mpeg"
    return send_file(path, mimetype=mimetype)


@assets_bp.route("/asset/<ts>/bg/<int:scene_idx>")
def asset_bg(ts, scene_idx):
    validate_ts(ts)
    p = safe_join(ts_path(ts), f"bg_{scene_idx:03d}.png")
    if os.path.exists(p):
        return send_file(p, mimetype="image/png")
    return "", 404


@assets_bp.route("/asset/<ts>/kling/<int:scene_idx>")
def asset_kling(ts, scene_idx):
    validate_ts(ts)
    p = safe_join(ts_path(ts), f"kling_{scene_idx:03d}.mp4")
    if os.path.exists(p):
        return send_file(p, mimetype="video/mp4")
    return "", 404


@assets_bp.route("/asset/<ts>/scene-trim/<int:scene_idx>")
def asset_scene_trim(ts, scene_idx):
    validate_ts(ts)
    p = safe_join(ts_path(ts), f"scene_{scene_idx:03d}.trim.mp4")
    if os.path.exists(p):
        return send_file(p, mimetype="video/mp4")
    return "", 404


@assets_bp.route("/asset/<ts>/scene/<int:scene_idx>")
def asset_scene(ts, scene_idx):
    validate_ts(ts)
    p = safe_join(ts_path(ts), f"scene_{scene_idx:03d}.mp4")
    if os.path.exists(p):
        return send_file(p, mimetype="video/mp4")
    return "", 404


@assets_bp.route("/asset/<ts>/scene-audio/<int:scene_idx>")
def asset_scene_audio(ts, scene_idx):
    validate_ts(ts)
    p = safe_join(ts_path(ts), f"audio_{scene_idx:03d}.m4a")
    if os.path.exists(p):
        return send_file(p, mimetype="audio/mp4")
    return "", 404


@assets_bp.route("/asset/<ts>/overlay")
def asset_overlay(ts):
    validate_ts(ts)
    p = safe_join(ts_path(ts), "overlaid.mp4")
    if os.path.exists(p):
        return send_file(p, mimetype="video/mp4")
    return "", 404


@assets_bp.route("/asset/character/<name>")
def asset_character(name):
    from analyze import character_meta as cmeta_mod
    if not _NAME_RE.match(name):
        abort(400)
    p = cmeta_mod.image_path(name)
    if p is not None and p.exists():
        return send_file(str(p), mimetype="image/png")
    return "", 404


@assets_bp.route("/asset/reference-video/<sha>")
def asset_reference_video(sha):
    """analyze ジョブの参考動画を Stage 1「素材編集」UI でプレビューさせる。"""
    if not _SHA256_RE.match(sha):
        abort(400)
    p = analyze_job.reference_video_path(sha)
    if not p or not os.path.exists(p):
        return "", 404
    ext = os.path.splitext(p)[1].lower()
    mimetype = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
    }.get(ext, "application/octet-stream")
    return send_file(p, mimetype=mimetype, conditional=True)


@assets_bp.route("/asset/location/<loc_id>/preview")
def asset_location_preview(loc_id):
    from analyze import location as loc_mod
    if not loc_mod.ID_RE.match(loc_id or ""):
        abort(400)
    p = loc_mod.preview_path(loc_id)
    if p.exists():
        return send_file(str(p), mimetype="image/png")
    return "", 404
