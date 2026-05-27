"""Stage se の Blueprint: SE catalog 取得 + project の SE items 保存 + 自動配置 + 試聴 asset。

- GET  /api/se                     : 実ファイルが存在する SE catalog 一覧
- PUT  /api/projects/<ts>/se        : project の SE items を metadata.json に保存
- POST /api/projects/<ts>/se/auto   : 既存メタから SE 配置を自動導出して保存
- GET  /asset/se/<filename>         : SE 音源 (UI の試聴用)
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from flask import Blueprint, abort, jsonify, request, send_file

import compositor
import config
import io_utils
import project_state
import scene_gen
import se_library
import se_planner
import staged_pipeline
from routes._helpers import api_error, ts_path, validate_ts

se_bp = Blueprint("se", __name__)

_SE_FILE_RE = re.compile(r"^[\w\.\-]+$")


@se_bp.route("/api/se", methods=["GET"])
def api_list_se():
    """SE catalog (assets/se/ に実ファイルが存在するもの) を返す。"""
    return jsonify({"se": se_library.list_se()})


def _normalize_items(raw_items, valid_ids):
    """request の items を正規化する (不正 se_id / 型は ValueError)。"""
    out = []
    for it in raw_items:
        se_id = it.get("se_id")
        if se_id not in valid_ids:
            raise ValueError(f"unknown se_id: {se_id}")
        out.append({
            "time": max(0.0, float(it.get("time", 0.0))),
            "se_id": se_id,
            "volume": float(it.get("volume", config.SE_DEFAULT_VOLUME)),
            "source": it.get("source") or "manual",
            "reason": it.get("reason") or "",
        })
    return out


@se_bp.route("/api/projects/<ts>/se", methods=["PUT"])
def api_set_se(ts):
    """project の SE items を metadata.json に保存する。run_se が次回これを読む。"""
    validate_ts(ts)
    project_path = ts_path(ts)
    meta = project_state.read_metadata(project_path)
    if meta is None:
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)

    data = request.get_json(force=True) or {}
    valid_ids = {t.id for t in se_library.load_catalog()}
    try:
        items = _normalize_items(data.get("items") or [], valid_ids)
    except (TypeError, ValueError) as e:
        return api_error("SE_INVALID_ITEM", str(e), 400)

    se = meta.get("se") or {}
    se["items"] = items
    meta["se"] = se
    io_utils.atomic_write_json(
        os.path.join(project_path, "metadata.json"), meta)
    return jsonify({"se": meta["se"]})


@se_bp.route("/api/projects/<ts>/se/auto", methods=["POST"])
def api_auto_se(ts):
    """既存メタ (emotion / visual_intent / scene 境界) から SE 配置を自動導出して保存。"""
    validate_ts(ts)
    project_path = ts_path(ts)
    meta = project_state.read_metadata(project_path)
    if meta is None:
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)

    screenplay = staged_pipeline.load_project_screenplay(project_path)
    try:
        scene_videos = scene_gen.collect_scene_videos(screenplay, project_path)
    except (FileNotFoundError, RuntimeError) as e:
        return api_error("SE_SCENE_VIDEOS_MISSING", str(e), 409)

    offsets = compositor._scene_offsets_from_videos(scene_videos)
    items = se_planner.plan_se(screenplay, offsets)

    se = meta.get("se") or {}
    se["items"] = items
    se["auto_generated_at"] = datetime.now(timezone.utc).isoformat()
    meta["se"] = se
    io_utils.atomic_write_json(
        os.path.join(project_path, "metadata.json"), meta)
    return jsonify({"se": meta["se"]})


@se_bp.route("/asset/se/<filename>")
def asset_se(filename):
    """SE 音源を返す (= UI の試聴用)。assets/se/<filename>。"""
    if not _SE_FILE_RE.match(filename):
        abort(400)
    p = os.path.join(config.SE_DIR, filename)
    if not os.path.exists(p):
        return "", 404
    return send_file(p, mimetype="audio/mpeg", conditional=True)
