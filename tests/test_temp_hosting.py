"""platform_clients.temp_hosting のテスト (= boto3 を mock)。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_get_temp_host_raises_when_provider_unset(monkeypatch):
    monkeypatch.delenv("TEMP_HOST_PROVIDER", raising=False)
    from platform_clients import temp_hosting
    with pytest.raises(RuntimeError, match="TEMP_HOST_PROVIDER"):
        temp_hosting.get_temp_host()


def test_get_temp_host_r2_requires_full_env(monkeypatch):
    monkeypatch.setenv("TEMP_HOST_PROVIDER", "r2")
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
    from platform_clients import temp_hosting
    with pytest.raises(RuntimeError, match="R2 設定不足"):
        temp_hosting.get_temp_host()


def test_get_temp_host_s3_requires_full_env(monkeypatch):
    monkeypatch.setenv("TEMP_HOST_PROVIDER", "s3")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "y")
    from platform_clients import temp_hosting
    with pytest.raises(RuntimeError, match="S3 設定不足"):
        temp_hosting.get_temp_host()


def test_r2_host_uploads_and_returns_url(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP_HOST_PROVIDER", "r2")
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setenv("R2_BUCKET", "bk")
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://cdn.example.com/path/")

    fake_client = MagicMock()
    fake_boto3 = MagicMock()
    fake_boto3.client.return_value = fake_client
    monkeypatch.setitem(__import__("sys").modules, "boto3", fake_boto3)

    src = tmp_path / "v.mp4"
    src.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)

    from platform_clients import temp_hosting
    host = temp_hosting.get_temp_host()
    key, url = host.upload(src, ttl=600)

    assert key.startswith("smg-temp/")
    assert key.endswith(".mp4")
    # public_base_url が指定されていれば pre-signed は使わない
    assert url.startswith("https://cdn.example.com/path/smg-temp/")
    assert fake_client.put_object.called
    pa, pkw = fake_client.put_object.call_args
    assert pkw["Bucket"] == "bk"
    assert pkw["ContentType"] == "video/mp4"


def test_r2_host_uses_presigned_url_when_no_public_base(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP_HOST_PROVIDER", "r2")
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setenv("R2_BUCKET", "bk")
    monkeypatch.delenv("R2_PUBLIC_BASE_URL", raising=False)

    fake_client = MagicMock()
    fake_client.generate_presigned_url.return_value = "https://signed.example/"
    fake_boto3 = MagicMock()
    fake_boto3.client.return_value = fake_client
    monkeypatch.setitem(__import__("sys").modules, "boto3", fake_boto3)

    src = tmp_path / "x.mp4"
    src.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 50)

    from platform_clients import temp_hosting
    host = temp_hosting.get_temp_host()
    _, url = host.upload(src)
    assert url == "https://signed.example/"
    fake_client.generate_presigned_url.assert_called_once()


def test_host_delete_swallows_exceptions(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP_HOST_PROVIDER", "r2")
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setenv("R2_BUCKET", "bk")

    fake_client = MagicMock()
    fake_client.delete_object.side_effect = RuntimeError("network")
    fake_boto3 = MagicMock()
    fake_boto3.client.return_value = fake_client
    monkeypatch.setitem(__import__("sys").modules, "boto3", fake_boto3)

    from platform_clients import temp_hosting
    host = temp_hosting.get_temp_host()
    # delete は例外を投げない (= cleanup で publish 結果を壊さない)
    host.delete("smg-temp/x.mp4")
