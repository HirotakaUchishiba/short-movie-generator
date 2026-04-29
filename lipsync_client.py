import json
import logging
import math
import os
import subprocess as sp
import time

import fal_client
import requests

import config
from fal_runner import FalJobTimeoutError, run_with_timeout

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
    # 自前 watchdog タイムアウトは retry
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


def _apply_fal_sync(video_path: str, audio_path: str, output_path: str) -> None:
    _ensure_key()

    video_url = fal_client.upload_file(video_path)
    audio_url = fal_client.upload_file(audio_path)

    last_exc: BaseException | None = None
    for attempt in range(MAX_RETRIES):
        try:
            result = run_with_timeout(
                lambda: fal_client.subscribe(
                    _FAL_MODEL_ID,
                    arguments={
                        "video_url": video_url,
                        "audio_url": audio_url,
                        "model": config.LIPSYNC_MODEL,
                        "sync_mode": config.LIPSYNC_SYNC_MODE,
                    },
                    with_logs=True,
                    on_queue_update=lambda update: None,
                ),
                timeout_sec=config.FAL_LIPSYNC_TIMEOUT_SEC,
                name=f"lipsync-attempt{attempt + 1}",
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


# ─────────────────── DomoAI talking-avatar ───────────────────


def _domoai_headers() -> dict:
    if not config.DOMOAI_API_KEY:
        raise LipsyncClientError(
            "DOMOAI_API_KEY が未設定。.env に DOMOAI_API_KEY=<key> を追加してください。"
        )
    return {"Authorization": f"Bearer {config.DOMOAI_API_KEY}"}


def _ffprobe_duration(path: str) -> float:
    r = sp.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", path],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise LipsyncClientError(f"ffprobe 失敗: {path}: {r.stderr[-200:]}")
    return float(json.loads(r.stdout)["format"]["duration"])


def _domoai_upload(local_path: str) -> str:
    """presigned URL 経由でファイルをアップロードし domoai_uri を返す。"""
    base = config.DOMOAI_BASE_URL.rstrip("/")
    filename = os.path.basename(local_path)

    r = requests.post(
        f"{base}/upload/file",
        headers={**_domoai_headers(), "Content-Type": "application/json"},
        json={"filename": filename},
        timeout=30,
    )
    r.raise_for_status()
    info = r.json().get("data") or {}
    presigned = info.get("presigned_url")
    domoai_uri = info.get("domoai_uri")
    extra_headers = info.get("headers") or {}
    if not presigned or not domoai_uri:
        raise LipsyncClientError(
            f"DomoAI upload レスポンス不正: {info}"
        )

    with open(local_path, "rb") as f:
        put_r = requests.put(presigned, data=f, headers=extra_headers,
                              timeout=300)
    if put_r.status_code >= 400:
        raise LipsyncClientError(
            f"DomoAI presigned PUT 失敗 ({put_r.status_code}): "
            f"{put_r.text[:200]}"
        )

    return domoai_uri


def _domoai_create_task(video_uri: str, audio_uri: str,
                        seconds: int) -> str:
    base = config.DOMOAI_BASE_URL.rstrip("/")
    payload = {
        "video": {"domoai_uri": video_uri},
        "audio": {"domoai_uri": audio_uri},
        "seconds": int(seconds),
        "model": config.DOMOAI_LIPSYNC_MODEL,
    }
    r = requests.post(
        f"{base}/video/talking-avatar",
        headers={**_domoai_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if r.status_code >= 400:
        raise LipsyncClientError(
            f"DomoAI talking-avatar 作成失敗 ({r.status_code}): "
            f"{r.text[:300]}"
        )
    data = r.json().get("data") or {}
    task_id = data.get("task_id")
    if not task_id:
        raise LipsyncClientError(
            f"DomoAI レスポンスに task_id が無い: {r.json()}"
        )
    return task_id


def _domoai_poll_until_done(task_id: str) -> str:
    """task が SUCCESS になるまで polling し、output_videos[0].url を返す。"""
    base = config.DOMOAI_BASE_URL.rstrip("/")
    interval = max(1.0, float(config.DOMOAI_POLL_INTERVAL_SEC))
    deadline = time.monotonic() + float(config.DOMOAI_POLL_TIMEOUT_SEC)

    while True:
        r = requests.get(
            f"{base}/tasks/{task_id}",
            headers=_domoai_headers(),
            timeout=30,
        )
        if r.status_code >= 400:
            raise LipsyncClientError(
                f"DomoAI task 取得失敗 ({r.status_code}): {r.text[:200]}"
            )
        data = r.json().get("data") or {}
        status = data.get("status")

        if status == "SUCCESS":
            outputs = data.get("output_videos") or []
            if not outputs or not outputs[0].get("url"):
                raise LipsyncClientError(
                    f"DomoAI SUCCESS だが output_videos が空: {data}"
                )
            return outputs[0]["url"]

        if status in {"FAILED", "CANCELED"}:
            raise LipsyncClientError(
                f"DomoAI ジョブ失敗 (status={status}): {data}"
            )

        if time.monotonic() > deadline:
            raise LipsyncClientError(
                f"DomoAI ポーリングタイムアウト ({config.DOMOAI_POLL_TIMEOUT_SEC}s) "
                f"task_id={task_id} 最終status={status}"
            )

        logger.debug("DomoAI task=%s status=%s — %.1fs後にretry",
                       task_id, status, interval)
        time.sleep(interval)


def _apply_domoai_sync(video_path: str, audio_path: str,
                       output_path: str) -> None:
    audio_dur = _ffprobe_duration(audio_path)
    seconds = max(1, min(int(math.ceil(audio_dur)),
                          int(config.DOMOAI_MAX_DURATION_SEC)))
    if audio_dur > config.DOMOAI_MAX_DURATION_SEC:
        logger.warning(
            "DomoAI: 音声 %.2fs が上限 %ds を超過。clamp して送信します。",
            audio_dur, config.DOMOAI_MAX_DURATION_SEC,
        )

    logger.info("DomoAI lipsync: アップロード開始")
    video_uri = _domoai_upload(video_path)
    audio_uri = _domoai_upload(audio_path)

    logger.info("DomoAI lipsync: ジョブ作成 (seconds=%d)", seconds)
    task_id = _domoai_create_task(video_uri, audio_uri, seconds)
    logger.info("DomoAI lipsync: task_id=%s でポーリング開始", task_id)

    result_url = _domoai_poll_until_done(task_id)

    resp = requests.get(result_url, timeout=300)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(resp.content)
    logger.info("DomoAI lipsync: 完了 → %s", output_path)


# ─────────────────── Sync.so (公式 API) ───────────────────


def _syncso_headers() -> dict:
    if not config.SYNCSO_API_KEY:
        raise LipsyncClientError(
            "SYNC_API_KEY が未設定。.env に SYNC_API_KEY=<key> を追加してください。"
        )
    return {"x-api-key": config.SYNCSO_API_KEY}


def _check_syncso_file_size(path: str) -> None:
    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb > config.SYNCSO_MAX_FILE_MB:
        raise LipsyncClientError(
            f"Sync.so multipart 上限 {config.SYNCSO_MAX_FILE_MB}MB を超過: "
            f"{path} ({size_mb:.1f}MB)"
        )


def _syncso_create_task(video_path: str, audio_path: str) -> str:
    base = config.SYNCSO_BASE_URL.rstrip("/")
    url = f"{base}/generate"

    with open(video_path, "rb") as vf, open(audio_path, "rb") as af:
        files = {
            "video": (os.path.basename(video_path), vf, "video/mp4"),
            "audio": (os.path.basename(audio_path), af, "audio/mp4"),
        }
        data = {
            "model": config.SYNCSO_LIPSYNC_MODEL,
            "options[sync_mode]": config.LIPSYNC_SYNC_MODE,
        }
        r = requests.post(
            url,
            headers=_syncso_headers(),
            files=files,
            data=data,
            timeout=120,
        )

    if r.status_code >= 400:
        raise LipsyncClientError(
            f"Sync.so generate 作成失敗 ({r.status_code}): {r.text[:300]}"
        )
    body = r.json()
    task_id = body.get("id")
    if not task_id:
        raise LipsyncClientError(
            f"Sync.so レスポンスに id が無い: {body}"
        )
    return task_id


def _syncso_poll_until_done(task_id: str) -> str:
    """COMPLETED まで polling し outputUrl を返す。"""
    base = config.SYNCSO_BASE_URL.rstrip("/")
    interval = max(1.0, float(config.SYNCSO_POLL_INTERVAL_SEC))
    deadline = time.monotonic() + float(config.SYNCSO_POLL_TIMEOUT_SEC)

    while True:
        r = requests.get(
            f"{base}/generate/{task_id}",
            headers=_syncso_headers(),
            timeout=30,
        )
        if r.status_code >= 400:
            raise LipsyncClientError(
                f"Sync.so generate 取得失敗 ({r.status_code}): {r.text[:200]}"
            )
        body = r.json() or {}
        status = body.get("status")

        if status == "COMPLETED":
            # OpenAPI は outputUrl だが quickstart は output_url。両対応。
            url = body.get("outputUrl") or body.get("output_url")
            if not url:
                raise LipsyncClientError(
                    f"Sync.so COMPLETED だが output URL が空: {body}"
                )
            return url

        if status in {"FAILED", "REJECTED"}:
            raise LipsyncClientError(
                f"Sync.so ジョブ失敗 (status={status}): {body}"
            )

        if time.monotonic() > deadline:
            raise LipsyncClientError(
                f"Sync.so ポーリングタイムアウト ({config.SYNCSO_POLL_TIMEOUT_SEC}s) "
                f"id={task_id} 最終status={status}"
            )

        logger.debug("Sync.so id=%s status=%s — %.1fs後にretry",
                       task_id, status, interval)
        time.sleep(interval)


def _apply_syncso_sync(video_path: str, audio_path: str,
                       output_path: str) -> None:
    _check_syncso_file_size(video_path)
    _check_syncso_file_size(audio_path)

    logger.info("Sync.so lipsync: ジョブ作成 (model=%s)",
                config.SYNCSO_LIPSYNC_MODEL)
    task_id = _syncso_create_task(video_path, audio_path)
    logger.info("Sync.so lipsync: id=%s でポーリング開始", task_id)

    result_url = _syncso_poll_until_done(task_id)

    resp = requests.get(result_url, timeout=300)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(resp.content)
    logger.info("Sync.so lipsync: 完了 → %s", output_path)


_PROVIDERS = {
    "fal-sync": _apply_fal_sync,
    "domoai": _apply_domoai_sync,
    "syncso": _apply_syncso_sync,
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
