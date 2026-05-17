import logging
import os
import time

import requests

import config
import io_utils
from common.api_client import APIClientError

logger = logging.getLogger(__name__)


class LipsyncClientError(APIClientError):
    """Sync.so lipsync 固有のエラー。`APIClientError` を継承 (= §3.2)。"""


def _parse_syncso_response(r: requests.Response, *, context: str) -> dict:
    """Sync.so 応答を dict として安全に parse する。

    JSON parse 失敗や dict でない応答を LipsyncClientError に正規化し、
    caller (= stage runner) の error 分類が機能するようにする。
    """
    try:
        body = r.json()
    except ValueError as e:
        raise LipsyncClientError(
            f"Sync.so {context} JSON parse 失敗 (status={r.status_code})"
        ) from e
    if not isinstance(body, dict):
        raise LipsyncClientError(
            f"Sync.so {context} 応答が dict ではない "
            f"(status={r.status_code}, type={type(body).__name__})"
        )
    return body


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
            timeout=config.LIPSYNC_HTTP_TIMEOUT_UPLOAD_SEC,
        )

    if r.status_code >= 400:
        logger.debug(
            "Sync.so generate 作成 response body (truncated 200ch): %s",
            (r.text or "")[:200],
        )
        raise LipsyncClientError(
            f"Sync.so generate 作成失敗 (status={r.status_code})"
        )
    body = _parse_syncso_response(r, context="generate 作成")
    task_id = body.get("id")
    if not task_id:
        raise LipsyncClientError(
            f"Sync.so レスポンスに id が無い (keys={sorted(body.keys()) if isinstance(body, dict) else type(body).__name__})"
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
            logger.debug(
                "Sync.so generate 取得 response body (truncated 200ch): %s",
                (r.text or "")[:200],
            )
            raise LipsyncClientError(
                f"Sync.so generate 取得失敗 (status={r.status_code})"
            )
        body = _parse_syncso_response(r, context="generate 取得")
        status = body.get("status")

        if status == "COMPLETED":
            # OpenAPI は outputUrl だが quickstart は output_url。両対応。
            url = body.get("outputUrl") or body.get("output_url")
            if not url:
                raise LipsyncClientError(
                    f"Sync.so COMPLETED だが output URL が空 (keys={sorted(body.keys())})"
                )
            return url

        if status in {"FAILED", "REJECTED"}:
            err_detail = body.get("error") or body.get("message") or "(no detail)"
            raise LipsyncClientError(
                f"Sync.so ジョブ失敗 (sync_status={status}, error={err_detail})"
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

    resp = requests.get(result_url, timeout=config.LIPSYNC_HTTP_TIMEOUT_DOWNLOAD_SEC)
    resp.raise_for_status()
    io_utils.atomic_write_bytes(output_path, resp.content)
    logger.info("Sync.so lipsync: 完了 → %s", output_path)


def apply(video_path: str, audio_path: str, output_path: str) -> None:
    _apply_syncso_sync(video_path, audio_path, output_path)
