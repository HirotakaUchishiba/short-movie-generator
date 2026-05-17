import logging
import os
import time

import fal_client
import requests
from PIL import Image

import config
import io_utils
from common.api_client import APIClientError
from fal_runner import FalJobTimeoutError, run_with_timeout

logger = logging.getLogger(__name__)

MODEL_ID = "fal-ai/kling-video/v3/standard/image-to-video"

MAX_RETRIES = 5
BACKOFF_SECONDS = [10, 20, 40, 80, 120]


class FalClientError(APIClientError):
    """fal.ai Kling 固有のエラー。`APIClientError` を継承 (= §3.2)。"""


def _ensure_key() -> None:
    key = config.FAL_API_KEY
    if key:
        os.environ["FAL_KEY"] = key


def _pick_duration(audio_duration: float) -> int:
    """Kling V3 standard は 5 または 10 秒のみ受理するためsnapする。

    config.KLING_DURATION_TOLERANCE_RATIO までは 5s クリップで吸収し、
    超過分は下流で slow_mo 延長する (5.01s で即 10s 切替を防いでコスト最適化)。
    """
    tol = float(config.KLING_DURATION_TOLERANCE_RATIO)
    if audio_duration <= 5.0 * tol:
        return 5
    return 10


def _classify_error(exc: BaseException) -> str:
    # 自前 watchdog タイムアウトは retry (fal の stuck job ならリトライで解決する可能性)
    if isinstance(exc, FalJobTimeoutError):
        return "retry"

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


def generate_video(image_path: str, prompt: str, output_path: str,
                   audio_duration: float = 5.0) -> None:
    _ensure_key()

    image_url = fal_client.encode_image(Image.open(image_path))
    duration = _pick_duration(audio_duration)

    last_exc: BaseException | None = None
    for attempt in range(MAX_RETRIES):
        try:
            result = run_with_timeout(
                lambda: fal_client.subscribe(
                    MODEL_ID,
                    arguments={
                        "start_image_url": image_url,
                        "prompt": prompt,
                        "duration": str(duration),
                        "generate_audio": False,
                    },
                    with_logs=True,
                    on_queue_update=lambda update: None,
                ),
                timeout_sec=config.FAL_KLING_TIMEOUT_SEC,
                name=f"kling-attempt{attempt + 1}",
            )

            video_url = result["video"]["url"]
            resp = requests.get(video_url, timeout=300)
            resp.raise_for_status()
            io_utils.atomic_write_bytes(output_path, resp.content)
            return

        except Exception as exc:
            last_exc = exc
            classification = _classify_error(exc)
            if classification == "fail":
                raise FalClientError(f"fal.ai 非リトライエラー: {exc}") from exc

            if attempt >= MAX_RETRIES - 1:
                break

            # 例外に response があれば Retry-After ヘッダを尊重する
            retry_after_hdr = None
            resp_obj = getattr(exc, "response", None)
            if resp_obj is not None:
                hdrs = getattr(resp_obj, "headers", None)
                if hdrs is not None:
                    retry_after_hdr = io_utils.parse_retry_after(hdrs.get("Retry-After"))
            wait = io_utils.next_backoff_seconds(
                attempt, BACKOFF_SECONDS, retry_after=retry_after_hdr
            )
            logger.warning(
                "fal.ai エラー (%s回目/%s): %s — %.1f秒後にリトライ%s",
                attempt + 1, MAX_RETRIES, exc, wait,
                " (Retry-After 由来)" if retry_after_hdr is not None else "",
            )
            time.sleep(wait)

    raise FalClientError(f"fal.ai リトライ上限超過: {last_exc}") from last_exc
