"""IG / TikTok の Pull URL 用一時ホスティング (= S3 / R2 互換ストレージ)。

Tailscale-only 運用なので preview_server を public 露出させない。代わりに
S3 / R2 互換 bucket に短期 (= 1 時間 TTL) で動画を上げ、pre-signed URL を
IG Graph API / TikTok Display API に渡す。

設定は環境変数 ``TEMP_HOST_PROVIDER``:
    - ``r2`` (= Cloudflare R2): R2_ACCOUNT_ID / R2_ACCESS_KEY_ID /
      R2_SECRET_ACCESS_KEY / R2_BUCKET / R2_PUBLIC_BASE_URL (任意)
    - ``s3`` (= AWS S3): AWS_REGION / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
      S3_BUCKET
    - 未設定 / ``none``: ``RuntimeError``。半自動経路 (= clipboard) を使う

依存: boto3 (= R2 / S3 共通の S3 互換 client)。lazy import で全プロジェクトに
強制しない。``pip install boto3`` してから env を設定する。
"""
from __future__ import annotations

import logging
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TTL_SEC = 3600
_TEXT_CONTENT_TYPE = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
}


class TempHost(ABC):
    """IG/TikTok に渡す pre-signed URL を発行する一時ホスト。"""

    @abstractmethod
    def upload(self, local_path: Path | str, *,
               ttl: int = DEFAULT_TTL_SEC) -> tuple[str, str]:
        """``local_path`` を upload し、``(key, public_url)`` を返す。"""

    @abstractmethod
    def delete(self, key: str) -> None:
        """`upload` が返した key を削除する (publish 完了後の cleanup 用)。"""


class _S3CompatibleHost(TempHost):
    """boto3 の S3 互換 client を共通化。R2 / S3 / MinIO で使える。"""

    def __init__(self, *, endpoint_url: str | None,
                 access_key: str, secret_key: str, region: str,
                 bucket: str, public_base_url: str | None) -> None:
        try:
            import boto3
        except ImportError as e:
            raise RuntimeError(
                "temp_hosting に boto3 が必要です: pip install boto3",
            ) from e
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self._bucket = bucket
        self._public_base_url = (public_base_url or "").rstrip("/")

    def upload(self, local_path: Path | str, *,
               ttl: int = DEFAULT_TTL_SEC) -> tuple[str, str]:
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        ext = path.suffix.lower()
        content_type = _TEXT_CONTENT_TYPE.get(ext, "application/octet-stream")
        key = f"smg-temp/{uuid.uuid4().hex}{ext}"
        with path.open("rb") as f:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=f,
                ContentType=content_type,
            )
        if self._public_base_url:
            url = f"{self._public_base_url}/{key}"
        else:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=int(ttl),
            )
        logger.info("[temp_hosting] uploaded %s → %s (ttl=%ds)",
                    path.name, key, ttl)
        return key, url

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            logger.info("[temp_hosting] deleted %s", key)
        except Exception as e:
            logger.warning("[temp_hosting] delete %s failed: %s", key, e)


def _build_r2() -> TempHost:
    account = os.getenv("R2_ACCOUNT_ID")
    access = os.getenv("R2_ACCESS_KEY_ID")
    secret = os.getenv("R2_SECRET_ACCESS_KEY")
    bucket = os.getenv("R2_BUCKET")
    if not all([account, access, secret, bucket]):
        raise RuntimeError(
            "R2 設定不足: R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / "
            "R2_SECRET_ACCESS_KEY / R2_BUCKET が必要",
        )
    return _S3CompatibleHost(
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        access_key=access,
        secret_key=secret,
        region="auto",
        bucket=bucket,
        public_base_url=os.getenv("R2_PUBLIC_BASE_URL"),
    )


def _build_s3() -> TempHost:
    access = os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    bucket = os.getenv("S3_BUCKET")
    region = os.getenv("AWS_REGION", "us-east-1")
    if not all([access, secret, bucket]):
        raise RuntimeError(
            "S3 設定不足: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / "
            "S3_BUCKET が必要",
        )
    return _S3CompatibleHost(
        endpoint_url=None,
        access_key=access,
        secret_key=secret,
        region=region,
        bucket=bucket,
        public_base_url=os.getenv("S3_PUBLIC_BASE_URL"),
    )


def get_temp_host() -> TempHost:
    """環境変数 ``TEMP_HOST_PROVIDER`` で指定された host を返す。

    Raises:
        RuntimeError: 未設定 or 設定不足。``INSTAGRAM_PUBLISH_MODE=api`` /
            ``TIKTOK_PUBLISH_MODE=api`` を有効にする前にここで失敗するので、
            半自動経路 (= ``mode=semi``) を使うときは get_temp_host を呼ばない。
    """
    provider = (os.getenv("TEMP_HOST_PROVIDER") or "").strip().lower()
    if provider == "r2":
        return _build_r2()
    if provider == "s3":
        return _build_s3()
    raise RuntimeError(
        "TEMP_HOST_PROVIDER=r2|s3 の設定が必要です (= IG/TikTok の API mode は "
        "動画ファイルを公開 https URL から PULL するため、preview_server を "
        "public 露出させない代わりに S3/R2 を一時ホストとして使います)",
    )
