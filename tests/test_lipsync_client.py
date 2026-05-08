from unittest.mock import MagicMock

import pytest

import lipsync_client


def _stub_syncso_env(monkeypatch, key: str = "test-syncso-key") -> None:
    monkeypatch.setattr(lipsync_client.config, "SYNCSO_API_KEY", key)
    monkeypatch.setattr(lipsync_client.config, "SYNCSO_BASE_URL",
                        "https://api.sync.so/v2")
    monkeypatch.setattr(lipsync_client.config, "SYNCSO_LIPSYNC_MODEL",
                        "lipsync-2")
    monkeypatch.setattr(lipsync_client.config, "SYNCSO_POLL_INTERVAL_SEC", 0.0)
    monkeypatch.setattr(lipsync_client.config, "SYNCSO_POLL_TIMEOUT_SEC", 60.0)
    monkeypatch.setattr(lipsync_client.config, "SYNCSO_MAX_FILE_MB", 20)
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_SYNC_MODE", "cut_off")


def test_apply_delegates_to_syncso(monkeypatch) -> None:
    mock_handler = MagicMock()
    monkeypatch.setattr(lipsync_client, "_apply_syncso_sync", mock_handler)

    lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")

    mock_handler.assert_called_once_with("/v.mp4", "/a.mp3", "/out.mp4")


def test_syncso_headers_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(lipsync_client.config, "SYNCSO_API_KEY", None)
    with pytest.raises(lipsync_client.LipsyncClientError) as exc:
        lipsync_client._syncso_headers()
    assert "SYNC_API_KEY" in str(exc.value)


def test_syncso_headers_uses_x_api_key(monkeypatch) -> None:
    monkeypatch.setattr(lipsync_client.config, "SYNCSO_API_KEY", "abc")
    h = lipsync_client._syncso_headers()
    assert h["x-api-key"] == "abc"
    assert "Authorization" not in h


def test_apply_syncso_sync_happy_path(tmp_path, monkeypatch) -> None:
    """multipart upload → poll(PROCESSING→COMPLETED) → outputUrl DL のフロー検証。"""
    _stub_syncso_env(monkeypatch)

    create_calls: list[dict] = []
    poll_calls: list[int] = []

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        assert url == "https://api.sync.so/v2/generate"
        assert headers == {"x-api-key": "test-syncso-key"}
        assert "video" in files and "audio" in files
        create_calls.append(dict(data))
        r = MagicMock()
        r.status_code = 201
        r.json.return_value = {"id": "gen-uuid-1", "status": "PENDING"}
        return r

    def fake_get(url, headers=None, timeout=None):
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status.return_value = None
        if url.endswith("/generate/gen-uuid-1"):
            poll_calls.append(1)
            if len(poll_calls) < 2:
                r.json.return_value = {"id": "gen-uuid-1", "status": "PROCESSING"}
            else:
                r.json.return_value = {
                    "id": "gen-uuid-1",
                    "status": "COMPLETED",
                    "outputUrl": "https://cdn.sync.so/result.mp4",
                }
        else:
            r.content = b"FINAL_LIPSYNCED_BYTES"
        return r

    monkeypatch.setattr(lipsync_client.requests, "post", fake_post)
    monkeypatch.setattr(lipsync_client.requests, "get", fake_get)

    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.m4a"
    out = tmp_path / "out.mp4"
    video.write_bytes(b"VIDEO")
    audio.write_bytes(b"AUDIO")

    lipsync_client._apply_syncso_sync(str(video), str(audio), str(out))

    assert out.read_bytes() == b"FINAL_LIPSYNCED_BYTES"
    assert len(create_calls) == 1
    assert create_calls[0]["model"] == "lipsync-2"
    assert create_calls[0]["options[sync_mode]"] == "cut_off"
    assert len(poll_calls) == 2  # PROCESSING → COMPLETED


def test_apply_syncso_sync_accepts_snake_case_output_url(
    tmp_path, monkeypatch,
) -> None:
    """quickstart は output_url を返すので両 keyに対応していること。"""
    _stub_syncso_env(monkeypatch)

    def fake_post(url, **_):
        r = MagicMock(); r.status_code = 201
        r.json.return_value = {"id": "g1", "status": "PENDING"}
        return r

    def fake_get(url, **_):
        r = MagicMock(); r.status_code = 200
        r.raise_for_status.return_value = None
        if "/generate/" in url:
            r.json.return_value = {
                "id": "g1",
                "status": "COMPLETED",
                "output_url": "https://cdn/x.mp4",  # snake_case
            }
        else:
            r.content = b"X"
        return r

    monkeypatch.setattr(lipsync_client.requests, "post", fake_post)
    monkeypatch.setattr(lipsync_client.requests, "get", fake_get)

    video = tmp_path / "v.mp4"; audio = tmp_path / "a.m4a"
    video.write_bytes(b"V"); audio.write_bytes(b"A")
    out = tmp_path / "o.mp4"

    lipsync_client._apply_syncso_sync(str(video), str(audio), str(out))
    assert out.read_bytes() == b"X"


def test_apply_syncso_sync_raises_on_rejected(tmp_path, monkeypatch) -> None:
    _stub_syncso_env(monkeypatch)

    def fake_post(url, **_):
        r = MagicMock(); r.status_code = 201
        r.json.return_value = {"id": "g2", "status": "PENDING"}
        return r

    def fake_get(url, **_):
        r = MagicMock(); r.status_code = 200
        r.raise_for_status.return_value = None
        r.json.return_value = {
            "id": "g2", "status": "REJECTED",
            "error": "audio too short",
        }
        return r

    monkeypatch.setattr(lipsync_client.requests, "post", fake_post)
    monkeypatch.setattr(lipsync_client.requests, "get", fake_get)

    video = tmp_path / "v.mp4"; audio = tmp_path / "a.m4a"
    video.write_bytes(b"V"); audio.write_bytes(b"A")

    with pytest.raises(lipsync_client.LipsyncClientError) as exc:
        lipsync_client._apply_syncso_sync(
            str(video), str(audio), str(tmp_path / "o.mp4"))
    assert "REJECTED" in str(exc.value)


def test_apply_syncso_sync_rejects_oversized_file(tmp_path, monkeypatch) -> None:
    _stub_syncso_env(monkeypatch)
    monkeypatch.setattr(lipsync_client.config, "SYNCSO_MAX_FILE_MB", 1)

    video = tmp_path / "v.mp4"; audio = tmp_path / "a.m4a"
    video.write_bytes(b"X" * (2 * 1024 * 1024))  # 2MB
    audio.write_bytes(b"A")

    with pytest.raises(lipsync_client.LipsyncClientError) as exc:
        lipsync_client._apply_syncso_sync(
            str(video), str(audio), str(tmp_path / "o.mp4"))
    assert "20MB" not in str(exc.value)  # MAX を 1MB に変えたので
    assert "1MB" in str(exc.value).replace(" ", "") \
        or "1.0" in str(exc.value)  # ゆるめに


def test_apply_syncso_sync_4xx_creates_clear_error(tmp_path, monkeypatch) -> None:
    _stub_syncso_env(monkeypatch)

    def fake_post(url, **_):
        r = MagicMock(); r.status_code = 401
        r.text = "invalid api key"
        return r

    monkeypatch.setattr(lipsync_client.requests, "post", fake_post)

    video = tmp_path / "v.mp4"; audio = tmp_path / "a.m4a"
    video.write_bytes(b"V"); audio.write_bytes(b"A")

    with pytest.raises(lipsync_client.LipsyncClientError) as exc:
        lipsync_client._apply_syncso_sync(
            str(video), str(audio), str(tmp_path / "o.mp4"))
    assert "401" in str(exc.value)
