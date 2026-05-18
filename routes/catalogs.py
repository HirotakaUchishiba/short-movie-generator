"""``/api/characters`` + ``/api/presets`` の Blueprint。

frontend が dropdown / 一覧 UI を組むための static read-only catalog を
返す 2 endpoint。preview_server.py から段階移行 (= §3.1.2)。
"""
from __future__ import annotations

from flask import Blueprint, jsonify

catalogs_bp = Blueprint("catalogs", __name__)


@catalogs_bp.route("/api/characters", methods=["GET"])
def api_list_characters():
    """利用可能な resolved id (= <base>__<wardrobe> / <base>) 一覧。

    新ネスト構造 (characters/<base>/<wardrobe>.png) と旧 flat レイアウトの
    両方に対応 (analyze.character_meta.list_character_images)。Stage 1 の
    登場人物選択 UI から呼ばれる。
    """
    from analyze import character_meta as cmeta_mod
    return jsonify({"characters": cmeta_mod.list_character_images()})


@catalogs_bp.route("/api/presets", methods=["GET"])
def api_presets():
    """preset ライブラリ全部をフロントに返す (= visual cue 系 UI dropdown 用)。"""
    import config as _config
    return jsonify({
        "libraries": _config.PROMPT_PRESET_LIBRARIES,
        "labels_ja": _config.PRESET_LABELS_JA,
        "category_labels_ja": _config.PRESET_CATEGORY_LABELS_JA,
        "emotion_default_preset_ids": _config.EMOTION_DEFAULT_PRESET_IDS,
    })
