"""``/api/character-metas*`` の Blueprint (= キャラ voice メタ CRUD)。

preview_server.py から段階移行 (locations / reference_videos に続く)。
各 character_meta は ``characters/<base>/voice.json`` に保存される
(= base ID 単位、衣装で voice は変わらない)。
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from routes._helpers import api_error

logger = logging.getLogger(__name__)

character_metas_bp = Blueprint("character_metas", __name__)


@character_metas_bp.route("/api/character-metas", methods=["GET"])
def api_list_character_metas():
    from analyze import character_meta as cmeta_mod
    metas = []
    for cid in cmeta_mod.list_character_metas():
        try:
            metas.append(cmeta_mod.load_character_meta(cid).to_dict())
        except Exception as e:
            logger.warning("character_meta %s 読み込み失敗: %s", cid, e)
    images = cmeta_mod.list_character_images()
    return jsonify({"character_metas": metas, "image_ids": images})


@character_metas_bp.route("/api/character-metas/<char_id>", methods=["GET"])
def api_get_character_meta(char_id):
    from analyze import character_meta as cmeta_mod
    try:
        return jsonify(cmeta_mod.load_character_meta(char_id).to_dict())
    except ValueError as e:
        return api_error("CHARACTER_META_INVALID", str(e), 400)


@character_metas_bp.route("/api/character-metas/<char_id>", methods=["PUT"])
def api_update_character_meta(char_id):
    from analyze import character_meta as cmeta_mod
    if not cmeta_mod.ID_RE.match(char_id):
        return api_error("CHARACTER_META_INVALID_ID", "invalid id", 400)
    data = request.get_json(force=True) or {}
    data["id"] = char_id
    try:
        meta = cmeta_mod.CharacterMeta.from_dict(data)
        cmeta_mod.save_character_meta(meta)
    except ValueError as e:
        return api_error("CHARACTER_META_INVALID", str(e), 400)
    return jsonify(meta.to_dict())


@character_metas_bp.route("/api/character-metas/<char_id>", methods=["DELETE"])
def api_delete_character_meta(char_id):
    from analyze import character_meta as cmeta_mod
    try:
        deleted = cmeta_mod.delete_character_meta(char_id)
    except ValueError as e:
        return api_error("CHARACTER_META_INVALID", str(e), 400)
    if not deleted:
        return api_error(
            "CHARACTER_META_NOT_FOUND",
            f"character_meta not found: {char_id}", 404,
            character_id=char_id,
        )
    return jsonify({"id": char_id, "deleted": True})
