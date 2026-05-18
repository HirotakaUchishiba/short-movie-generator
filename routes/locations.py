"""``/api/locations*`` の Blueprint (= ロケ JSON カタログ CRUD)。

preview_server.py から段階移行。各 location は ``locations/<id>.json`` に
保存され、preview 画像は ``locations/<id>.preview.png`` (= /asset/location/
配下で配信、routes/assets.py に移管済み)。
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from routes._helpers import api_error

logger = logging.getLogger(__name__)

locations_bp = Blueprint("locations", __name__)


@locations_bp.route("/api/locations", methods=["GET"])
def api_list_locations():
    from analyze import location as loc_mod
    items = []
    for lid in loc_mod.list_locations():
        try:
            items.append(loc_mod.load_location(lid).to_dict())
        except Exception as e:
            logger.warning("location %s 読み込み失敗: %s", lid, e)
    return jsonify({"locations": items})


@locations_bp.route("/api/locations/<loc_id>", methods=["GET"])
def api_get_location(loc_id):
    from analyze import location as loc_mod
    try:
        return jsonify(loc_mod.load_location(loc_id).to_dict())
    except FileNotFoundError:
        return api_error(
            "LOCATION_NOT_FOUND",
            f"location not found: {loc_id}", 404,
            location_id=loc_id,
        )
    except ValueError as e:
        return api_error("LOCATION_INVALID", str(e), 400)


@locations_bp.route("/api/locations", methods=["POST"])
def api_create_location():
    from analyze import location as loc_mod
    data = request.get_json(force=True) or {}
    if not data.get("id"):
        return api_error("LOCATION_ID_REQUIRED", "id required", 400)
    try:
        loc = loc_mod.Location.from_dict(data)
        loc_mod.save_location(loc)
    except ValueError as e:
        return api_error("LOCATION_INVALID", str(e), 400)
    return jsonify(loc.to_dict()), 201


@locations_bp.route("/api/locations/<loc_id>", methods=["PUT"])
def api_update_location(loc_id):
    from analyze import location as loc_mod
    if not loc_mod.ID_RE.match(loc_id):
        return api_error("LOCATION_INVALID_ID", "invalid id", 400)
    data = request.get_json(force=True) or {}
    data["id"] = loc_id
    try:
        loc = loc_mod.Location.from_dict(data)
        loc_mod.save_location(loc)
    except ValueError as e:
        return api_error("LOCATION_INVALID", str(e), 400)
    return jsonify(loc.to_dict())


@locations_bp.route("/api/locations/<loc_id>", methods=["DELETE"])
def api_delete_location(loc_id):
    from analyze import location as loc_mod
    try:
        deleted = loc_mod.delete_location(loc_id)
    except ValueError as e:
        return api_error("LOCATION_INVALID", str(e), 400)
    if not deleted:
        return api_error(
            "LOCATION_NOT_FOUND",
            f"location not found: {loc_id}", 404,
            location_id=loc_id,
        )
    return jsonify({"id": loc_id, "deleted": True})
