"""``/api/config`` 系 Blueprint (= TTS / QA tag / フロント表示設定)。

`preview_server.py` から段階移行 (= cost / analytics に続く 3 番目)。
`_tts_pricing()` も Blueprint 内へ私有化する (= 5 routes すべてここから呼ぶ)。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

import config
import elevenlabs_client
import fal_video_client
import imagen_client
import progress_store
import video_analyzer
from cost_tracking import pricebook as cost_pricebook
from routes._helpers import api_error

config_bp = Blueprint("config", __name__)


def _tts_pricing() -> dict:
    """ElevenLabs の表示用設定 (= 文字単価倍率 + 単価情報)。

    ``usd_per_credit`` は ``data/pricebook.json`` から読む (= ハードコードしない)。
    実コスト見積もりは ``cost_tracking`` の履歴ベース算定が SSOT。
    """
    model = elevenlabs_client.MODEL_ID
    multiplier = elevenlabs_client.credit_multiplier(model)
    try:
        usd_per_credit = float(
            cost_pricebook.get_unit_prices("elevenlabs", model)
            .get("usd_per_credit", 0.0)
        )
    except KeyError:
        usd_per_credit = 0.0
    return {
        "model": model,
        "credit_multiplier": multiplier,
        "usd_per_credit": usd_per_credit,
        "available_models": elevenlabs_client.available_models(),
        "global_speed": float(config.TTS_GLOBAL_SPEED),
        "speed_min": 0.5,
        "speed_max": 2.0,
        "trim_silences": bool(getattr(config, "TTS_TRIM_LONG_SILENCES", False)),
        "max_silence_ms": float(getattr(config, "TTS_MAX_SILENCE_MS", 250)),
        "note": (
            f"{model} は1文字あたり {multiplier} credits 消費。"
            "実コストは data/cost_records.jsonl の履歴 median から算定。"
        ),
    }


@config_bp.route("/api/config/model", methods=["POST"])
def api_set_model():
    """ランタイムでELEVENLABSモデルを切替える。サーバ再起動するとenv値に戻る。"""
    data = request.get_json(force=True) or {}
    model = data.get("model")
    if not model:
        return api_error("CONFIG_MODEL_REQUIRED", "model required", 400)
    try:
        elevenlabs_client.set_model(model)
    except ValueError as e:
        return api_error("CONFIG_MODEL_INVALID", str(e), 400)
    return jsonify({"ok": True, "tts_pricing": _tts_pricing()})


@config_bp.route("/api/config/speed", methods=["POST"])
def api_set_speed():
    """ランタイムでTTSグローバル速度を変更する (0.5〜2.0)。"""
    data = request.get_json(force=True) or {}
    speed = data.get("speed")
    if not isinstance(speed, (int, float)):
        return api_error("CONFIG_SPEED_REQUIRED", "speed (number) required", 400)
    speed = float(speed)
    if speed < 0.5 or speed > 2.0:
        return api_error("CONFIG_SPEED_OUT_OF_RANGE", "speed must be 0.5〜2.0", 400, speed=speed)
    config.TTS_GLOBAL_SPEED = speed
    return jsonify({"ok": True, "tts_pricing": _tts_pricing()})


@config_bp.route("/api/config/silences", methods=["POST"])
def api_set_silences():
    """ランタイムで無音圧縮設定を変更する。"""
    data = request.get_json(force=True) or {}
    if "enabled" in data:
        config.TTS_TRIM_LONG_SILENCES = bool(data["enabled"])
    if "max_ms" in data:
        v = data["max_ms"]
        if not isinstance(v, (int, float)) or v < 50 or v > 2000:
            return api_error(
                "CONFIG_MAX_MS_OUT_OF_RANGE",
                "max_ms must be 50〜2000", 400, max_ms=v,
            )
        config.TTS_MAX_SILENCE_MS = float(v)
    return jsonify({"ok": True, "tts_pricing": _tts_pricing()})


@config_bp.route("/api/config/qa-tags", methods=["GET"])
def api_config_qa_tags():
    """QA failure タグの SSOT 配信。frontend RejectModal がここから取得する
    (= `qa/categories.py` を唯一の source of truth として drift を防ぐ)。"""
    from qa.categories import QA_AXIS_LABELS, QA_FAILURE_TAG_DEFS
    return jsonify({
        "tags": [dict(d) for d in QA_FAILURE_TAG_DEFS],
        "axis_labels": dict(QA_AXIS_LABELS),
    })


@config_bp.route("/api/config", methods=["GET"])
def api_config():
    """フロント表示用にconfig値を一部公開。"""
    voice_lib = [
        {"voice_id": v["voice_id"], "name": v.get("name"),
         "gender": v.get("gender"), "age": v.get("age"),
         "language": v.get("language")}
        for v in config.VOICE_LIBRARY
    ]
    return jsonify({
        "stages": progress_store.STAGES,
        "emotions": list(config.EMOTION_AUDIO_TAGS.keys()),
        "available_audio_tags": config.AVAILABLE_AUDIO_TAGS,
        "emotion_audio_tags": config.EMOTION_AUDIO_TAGS,
        "voice_library": voice_lib,
        "default_voice_id": config.ELEVENLABS_VOICE_ID,
        "default_stability": config.ELEVENLABS_VOICE_STABILITY,
        "default_similarity_boost": config.ELEVENLABS_VOICE_SIMILARITY_BOOST,
        "default_style": config.ELEVENLABS_VOICE_STYLE,
        "video_width": config.VIDEO_WIDTH,
        "video_height": config.VIDEO_HEIGHT,
        "subtitle_y_from_bottom": config.SUBTITLE_Y_FROM_BOTTOM,
        "tts_pricing": _tts_pricing(),
        "cost_models": {
            "tts": elevenlabs_client.MODEL_ID,
            "bg": imagen_client.MODEL,
            "kling": fal_video_client.MODEL_ID,
            "lipsync": config.SYNCSO_LIPSYNC_MODEL,
            "analyze": video_analyzer.ANALYZER_MODEL,
        },
    })
