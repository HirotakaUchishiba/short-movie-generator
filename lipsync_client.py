import logging
import os
import time

import fal_client
import requests

import config

logger = logging.getLogger(__name__)


class LipsyncClientError(Exception):
    pass


_FAL_MODEL_ID = "fal-ai/sync-lipsync"
MAX_RETRIES = 5
BACKOFF_SECONDS = [10, 20, 40, 80, 120]


def _ensure_key() -> None:
    key = config.FAL_API_KEY
    if key:
        os.environ["FAL_KEY"] = key


def _classify_error(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
    message = str(exc).lower()

    if "exhausted balance" in message or "user is locked" in message:
        return "fail"
    if status == 429 or "rate limit" in message or "too many requests" in message:
        return "retry"
    if status == 403:
        return "retry"
    if status is not None and 500 <= status < 600:
        return "retry"
    if status is not None and 400 <= status < 500:
        return "fail"
    if "timeout" in message or "timed out" in message:
        return "retry"
    return "retry"


def _apply_fal_sync(video_path: str, audio_path: str, output_path: str) -> None:
    _ensure_key()

    video_url = fal_client.upload_file(video_path)
    audio_url = fal_client.upload_file(audio_path)

    last_exc: BaseException | None = None
    for attempt in range(MAX_RETRIES):
        try:
            result = fal_client.subscribe(
                _FAL_MODEL_ID,
                arguments={
                    "video_url": video_url,
                    "audio_url": audio_url,
                    "model": config.LIPSYNC_MODEL,
                    "sync_mode": config.LIPSYNC_SYNC_MODE,
                },
                with_logs=True,
                on_queue_update=lambda update: None,
            )
            result_url = result["video"]["url"]
            resp = requests.get(result_url)
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return

        except Exception as exc:
            last_exc = exc
            classification = _classify_error(exc)
            if classification == "fail":
                raise LipsyncClientError(
                    f"fal.ai sync-lipsync 非リトライエラー: {exc}"
                ) from exc

            if attempt >= MAX_RETRIES - 1:
                break

            wait = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            logger.warning(
                "fal.ai sync-lipsync エラー (%d回目/%d): %s — %d秒後にリトライ",
                attempt + 1, MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)

    raise LipsyncClientError(
        f"fal.ai sync-lipsync リトライ上限超過: {last_exc}"
    ) from last_exc


_PROVIDERS = {
    "fal-sync": _apply_fal_sync,
}


def apply(video_path: str, audio_path: str, output_path: str) -> None:
    provider = config.LIPSYNC_PROVIDER
    handler = _PROVIDERS.get(provider)
    if handler is None:
        raise LipsyncClientError(
            f"未知のリップシンクプロバイダー: {provider} "
            f"(対応: {', '.join(_PROVIDERS.keys())})"
        )
    handler(video_path, audio_path, output_path)
