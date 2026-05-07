import logging
import os
import time

import requests
import config
from cost_tracking import pricebook as _pricebook

logger = logging.getLogger(__name__)

API_BASE = "https://api.elevenlabs.io/v1"
MODEL_ID = os.getenv("ELEVENLABS_MODEL", "eleven_v3")

MAX_RETRIES = 5
BACKOFF_SECONDS = [10, 20, 40, 80, 120]


class ElevenLabsClientError(Exception):
    pass


def _classify_status(status: int | None, body_lower: str) -> str:
    """HTTP status とレスポンス本文から retry / fail を分類する。

    fal_video_client._classify_error と同じ方針:
      - 残高切れ / アカウント停止系 → fail
      - 429 / 5xx / 接続不能 → retry
      - その他 4xx (= validation エラー等) → fail
    """
    if "exhausted" in body_lower or "out of credits" in body_lower:
        return "fail"
    if "user is locked" in body_lower or "voice not found" in body_lower:
        return "fail"
    if status == 429:
        return "retry"
    if status is not None and 500 <= status < 600:
        return "retry"
    if status is not None and 400 <= status < 500:
        return "fail"
    return "retry"


def _post_with_retry(url: str, headers: dict, json_body: dict,
                     timeout: float = 120.0) -> requests.Response:
    """ElevenLabs API への POST を retry 付きで叩く。

    429 / 5xx / 接続エラー → 指数バックオフで MAX_RETRIES 回まで。
    4xx (validation) や残高切れ → 即座に ElevenLabsClientError。
    """
    last_exc: BaseException | None = None
    last_status: int | None = None
    last_body: str = ""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(url, headers=headers, json=json_body,
                                 timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt >= MAX_RETRIES - 1:
                break
            wait = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            logger.warning(
                "ElevenLabs 接続エラー (%d回目/%d): %s — %d秒後にリトライ",
                attempt + 1, MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)
            continue

        if resp.ok:
            return resp

        last_status = resp.status_code
        last_body = resp.text or ""
        classification = _classify_status(resp.status_code, last_body.lower())
        if classification == "fail":
            raise ElevenLabsClientError(
                f"ElevenLabs 非リトライエラー ({resp.status_code}): "
                f"{last_body[:500]}"
            )
        if attempt >= MAX_RETRIES - 1:
            break
        wait = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
        logger.warning(
            "ElevenLabs %s (%d回目/%d) — %d秒後にリトライ: %s",
            resp.status_code, attempt + 1, MAX_RETRIES, wait,
            last_body[:200],
        )
        time.sleep(wait)

    if last_exc is not None:
        raise ElevenLabsClientError(
            f"ElevenLabs 接続リトライ上限超過: {last_exc}"
        ) from last_exc
    raise ElevenLabsClientError(
        f"ElevenLabs リトライ上限超過 ({last_status}): {last_body[:500]}"
    )

MODELS_WITHOUT_CONTEXT = {"eleven_v3"}

# UIから選択可能なモデルを制限する。
# v2 は [delivery] タグをそのまま音声化してしまうため除外。
# 他モデルは日本語が棒読みになるため、現状 v3 のみ許可。
ALLOWED_MODELS = {"eleven_v3"}


def credit_multiplier(model_id: str | None = None) -> float:
    """指定モデルの 1文字あたり credits 消費係数を pricebook から返す。

    pricebook 未登録モデルは 1.0 にフォールバック (= 課金しないモデル相当)。
    """
    target = model_id or MODEL_ID
    try:
        return float(
            _pricebook.get_unit_prices("elevenlabs", target).get(
                "credit_multiplier", 1.0,
            )
        )
    except (KeyError, FileNotFoundError):
        return 1.0


def set_model(model_id: str) -> None:
    """ランタイムでモデルを切替える。サーバ再起動するとenv値に戻る。"""
    global MODEL_ID
    if model_id not in ALLOWED_MODELS:
        raise ValueError(
            f"model not allowed: {model_id}. allowed={sorted(ALLOWED_MODELS)}"
        )
    MODEL_ID = model_id


def available_models() -> list[dict]:
    """UIから切替可能なモデル一覧 (ALLOWED_MODELS のみ、単価は pricebook から)。"""
    return [
        {
            "id": m,
            "credit_multiplier": credit_multiplier(m),
            "supports_context": m not in MODELS_WITHOUT_CONTEXT,
        }
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

    resp = _post_with_retry(
        f"{API_BASE}/text-to-speech/{voice_id}/with-timestamps",
        headers={**_headers(), "Content-Type": "application/json"},
        json_body=payload,
    )
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
