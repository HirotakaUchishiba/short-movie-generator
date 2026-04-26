import os

import requests
import config

API_BASE = "https://api.elevenlabs.io/v1"
MODEL_ID = os.getenv("ELEVENLABS_MODEL", "eleven_v3")

MODELS_WITHOUT_CONTEXT = {"eleven_v3"}

MODEL_CREDIT_MULTIPLIERS = {
    "eleven_v3": 2.0,
    "eleven_multilingual_v2": 1.0,
    "eleven_multilingual_v1": 1.0,
    "eleven_monolingual_v1": 1.0,
    "eleven_turbo_v2_5": 0.5,
    "eleven_turbo_v2": 0.5,
    "eleven_flash_v2_5": 0.33,
    "eleven_flash_v2": 0.33,
}

# UIから選択可能なモデルを制限する。
# v2 は [delivery] タグをそのまま音声化してしまうため除外。
# 他モデルは日本語が棒読みになるため、現状 v3 のみ許可。
ALLOWED_MODELS = {"eleven_v3"}


def credit_multiplier(model_id: str | None = None) -> float:
    """指定モデルの 1文字あたり credits 消費係数を返す。未知モデルは 1.0。"""
    return MODEL_CREDIT_MULTIPLIERS.get(model_id or MODEL_ID, 1.0)


def set_model(model_id: str) -> None:
    """ランタイムでモデルを切替える。サーバ再起動するとenv値に戻る。"""
    global MODEL_ID
    if model_id not in ALLOWED_MODELS:
        raise ValueError(
            f"model not allowed: {model_id}. allowed={sorted(ALLOWED_MODELS)}"
        )
    MODEL_ID = model_id


def available_models() -> list[dict]:
    """UIから切替可能なモデル一覧 (ALLOWED_MODELSのみ)。"""
    return [
        {"id": m, "credit_multiplier": MODEL_CREDIT_MULTIPLIERS.get(m, 1.0),
         "supports_context": m not in MODELS_WITHOUT_CONTEXT}
        for m in sorted(ALLOWED_MODELS)
    ]


def _headers():
    return {"xi-api-key": config.ELEVENLABS_API_KEY}


def generate_speech_with_timestamps(text: str, voice_id: str, output_path: str,
                                    stability: float = 0.3,
                                    similarity_boost: float = 0.85,
                                    style: float = 0.7, speed: float = 1.0,
                                    language: str = "ja",
                                    previous_text: str | None = None,
                                    next_text: str | None = None,
                                    keep_whitespace: bool = False) -> list[dict]:
    import base64
    import json as _json

    payload = {
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
        },
        "speed": speed,
    }
    if language:
        payload["language_code"] = language
    if MODEL_ID not in MODELS_WITHOUT_CONTEXT:
        if previous_text:
            payload["previous_text"] = previous_text
        if next_text:
            payload["next_text"] = next_text
    elif previous_text or next_text:
        import logging
        logging.getLogger(__name__).warning(
            "model=%s は前後文脈をサポートしていません。"
            "前後の発話を考慮した自然なつながりが必要なら "
            "ELEVENLABS_MODEL=eleven_multilingual_v2 を試してください。",
            MODEL_ID,
        )

    resp = requests.post(
        f"{API_BASE}/text-to-speech/{voice_id}/with-timestamps",
        headers={**_headers(), "Content-Type": "application/json"},
        json=payload,
    )
    if not resp.ok:
        import logging
        logging.getLogger(__name__).error(
            "ElevenLabs %s response: %s", resp.status_code, resp.text[:1500]
        )
    resp.raise_for_status()
    data = resp.json()

    audio_bytes = base64.b64decode(data["audio_base64"])
    with open(output_path, "wb") as f:
        f.write(audio_bytes)

    alignment = data.get("alignment", {})
    raw_chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    char_timestamps = []
    if keep_whitespace:
        for i, ch in enumerate(raw_chars):
            char_timestamps.append({
                "char": ch,
                "start": starts[i],
                "end": ends[i],
            })
    else:
        SKIP_CHARS = {" ", "\t", "\n", "、", "。", ",", "."}
        for i, ch in enumerate(raw_chars):
            if ch in SKIP_CHARS:
                continue
            char_timestamps.append({
                "char": ch,
                "start": starts[i],
                "end": ends[i],
            })

    timestamps_path = output_path.rsplit(".", 1)[0] + ".json"
    with open(timestamps_path, "w") as f:
        _json.dump(char_timestamps, f, indent=2)

    return char_timestamps
