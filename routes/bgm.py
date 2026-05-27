"""Stage bgm の Blueprint: BGM catalog 取得 + project の BGM 選択保存。

- GET  /api/bgm                  : 実ファイルが存在する BGM catalog 一覧
- PUT  /api/projects/<ts>/bgm    : project の BGM 選択を metadata.json に保存
"""
from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

import bgm_library
import config
import io_utils
import project_state
from routes._helpers import api_error, ts_path, validate_ts

bgm_bp = Blueprint("bgm", __name__)


@bgm_bp.route("/api/bgm", methods=["GET"])
def api_list_bgm():
    """BGM catalog (assets/bgm/ に実ファイルが存在するもの) を返す。"""
    return jsonify({"bgm": bgm_library.list_bgm()})


@bgm_bp.route("/api/projects/<ts>/bgm", methods=["PUT"])
def api_set_bgm(ts):
    """project の BGM 選択を metadata.json に保存する ({id, volume, ducking})。

    id は catalog の id または "none" (= BGM なし)。run_bgm が次回この値を読む。
    """
    validate_ts(ts)
    project_path = ts_path(ts)
    meta = project_state.read_metadata(project_path)
    if meta is None:
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)

    data = request.get_json(force=True) or {}
    bgm_id = data.get("id") or bgm_library.NONE_ID
    if bgm_id != bgm_library.NONE_ID:
        valid_ids = {t.id for t in bgm_library.load_catalog()}
        if bgm_id not in valid_ids:
            return api_error(
                "BGM_INVALID_ID", f"unknown bgm id: {bgm_id}", 400, bgm_id=bgm_id)

    try:
        volume = float(data.get("volume", config.BGM_VOLUME_RATIO))
    except (TypeError, ValueError):
        return api_error("BGM_INVALID_VOLUME", "volume must be a number", 400)
    ducking = bool(data.get("ducking", config.BGM_DUCKING_ENABLED))

    meta["bgm"] = {"id": bgm_id, "volume": volume, "ducking": ducking}
    io_utils.atomic_write_json(
        os.path.join(project_path, "metadata.json"), meta)
    return jsonify({"bgm": meta["bgm"]})
