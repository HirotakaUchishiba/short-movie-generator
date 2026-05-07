from unittest.mock import patch, MagicMock

import pytest

import lipsync_client


def test_apply_dispatches_to_fal_sync(monkeypatch) -> None:
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "fal-sync")
    mock_handler = MagicMock()
    monkeypatch.setitem(lipsync_client._PROVIDERS, "fal-sync", mock_handler)

    lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")

    mock_handler.assert_called_once_with("/v.mp4", "/a.mp3", "/out.mp4")


def test_apply_raises_on_unknown_provider(monkeypatch) -> None:
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "unknown-vendor")
    with pytest.raises(lipsync_client.LipsyncClientError) as exc:
        lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")
    assert "unknown-vendor" in str(exc.value)


def test_classify_error_retries_on_rate_limit() -> None:
    exc = Exception("rate limit exceeded")
    assert lipsync_client._classify_error(exc) == "retry"


def test_classify_error_retries_on_5xx() -> None:
    exc = Exception("server error")
    exc.status_code = 503
    assert lipsync_client._classify_error(exc) == "retry"


def test_classify_error_fails_on_4xx() -> None:
    exc = Exception("bad request")
    exc.status_code = 400
    assert lipsync_client._classify_error(exc) == "fail"


def test_classify_error_retries_on_403_transient() -> None:
    exc = Exception("forbidden")
    exc.status_code = 403
    assert lipsync_client._classify_error(exc) == "retry"


def test_classify_error_fails_on_exhausted_balance() -> None:
    exc = Exception("User is locked. Reason: Exhausted balance.")
    exc.status_code = 403
    assert lipsync_client._classify_error(exc) == "fail"


def test_classify_error_retries_on_timeout() -> None:
    exc = Exception("request timed out")
    assert lipsync_client._classify_error(exc) == "retry"


def test_apply_fal_sync_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_MODEL", "lipsync-1.9.0-beta")
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_SYNC_MODE", "cut_off")
    monkeypatch.setattr(lipsync_client.config, "FAL_API_KEY", "test-key")

    fake_fal = MagicMock()
    fake_fal.upload_file.side_effect = ["http://v", "http://a"]
    fake_fal.subscribe.return_value = {"video": {"url": "http://out.mp4"}}
    monkeypatch.setattr(lipsync_client, "fal_client", fake_fal)

    fake_resp = MagicMock()
    fake_resp.content = b"videodata"
    fake_resp.raise_for_status.return_value = None
    monkeypatch.setattr(lipsync_client.requests, "get",
                        lambda url, **_kw: fake_resp)

    out = tmp_path / "out.mp4"
    lipsync_client._apply_fal_sync("/v.mp4", "/a.mp3", str(out))

    assert out.read_bytes() == b"videodata"
    assert fake_fal.upload_file.call_count == 2
    args = fake_fal.subscribe.call_args
    assert args.args[0] == "fal-ai/sync-lipsync"
    assert args.kwargs["arguments"]["model"] == "lipsync-1.9.0-beta"
    assert args.kwargs["arguments"]["sync_mode"] == "cut_off"


def test_apply_fal_sync_raises_on_4xx(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lipsync_client.config, "FAL_API_KEY", "test-key")

    fake_fal = MagicMock()
    fake_fal.upload_file.return_value = "http://x"
    err = Exception("unauthorized")
    err.status_code = 401
    fake_fal.subscribe.side_effect = err
    monkeypatch.setattr(lipsync_client, "fal_client", fake_fal)

    with pytest.raises(lipsync_client.LipsyncClientError):
        lipsync_client._apply_fal_sync("/v.mp4", "/a.mp3", str(tmp_path / "out.mp4"))


# ─────────────────────── DomoAI provider ───────────────────────


def _stub_domoai_env(monkeypatch, key: str = "test-domoai-key") -> None:
    monkeypatch.setattr(lipsync_client.config, "DOMOAI_API_KEY", key)
    monkeypatch.setattr(lipsync_client.config, "DOMOAI_BASE_URL",
                        "https://api.domoai.com/v1")
    monkeypatch.setattr(lipsync_client.config, "DOMOAI_LIPSYNC_MODEL",
                        "talking-avatar-v1")
    monkeypatch.setattr(lipsync_client.config, "DOMOAI_POLL_INTERVAL_SEC", 0.0)
    monkeypatch.setattr(lipsync_client.config, "DOMOAI_POLL_TIMEOUT_SEC", 60.0)
    monkeypatch.setattr(lipsync_client.config, "DOMOAI_MAX_DURATION_SEC", 60)


def test_apply_dispatches_to_domoai(monkeypatch) -> None:
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "domoai")
    mock_handler = MagicMock()
    monkeypatch.setitem(lipsync_client._PROVIDERS, "domoai", mock_handler)

    lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")

    mock_handler.assert_called_once_with("/v.mp4", "/a.mp3", "/out.mp4")


def test_domoai_headers_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(lipsync_client.config, "DOMOAI_API_KEY", None)
    with pytest.raises(lipsync_client.LipsyncClientError) as exc:
        lipsync_client._domoai_headers()
    assert "DOMOAI_API_KEY" in str(exc.value)


def test_domoai_headers_uses_bearer(monkeypatch) -> None:
    monkeypatch.setattr(lipsync_client.config, "DOMOAI_API_KEY", "abc")
    h = lipsync_client._domoai_headers()
    assert h["Authorization"] == "Bearer abc"


def test_apply_domoai_sync_happy_path(tmp_path, monkeypatch) -> None:
    """upload → create task → poll(SUCCESS) → 動画 DL の一連を mock で検証。"""
    _stub_domoai_env(monkeypatch)

    monkeypatch.setattr(lipsync_client, "_ffprobe_duration", lambda p: 4.7)

    calls: list[tuple[str, str, dict]] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(("POST", url, json or {}))
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status.return_value = None
        if url.endswith("/upload/file"):
            r.json.return_value = {
                "data": {
                    "presigned_url": "https://s3.example/put?sig=xxx",
                    "headers": {"x-foo": "bar"},
                    "domoai_uri": f"jwt-for-{json['filename']}",
                }
            }
        elif url.endswith("/video/talking-avatar"):
            r.json.return_value = {"data": {"task_id": "task-uuid-1"}}
        return r

    def fake_put(url, data=None, headers=None, timeout=None):
        calls.append(("PUT", url, headers or {}))
        r = MagicMock()
        r.status_code = 200
        return r

    poll_calls: list[int] = []

    def fake_get(url, headers=None, timeout=None):
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status.return_value = None
        if url.endswith("/tasks/task-uuid-1"):
            poll_calls.append(1)
            # 1回目 PROCESSING、2回目 SUCCESS で返す
            if len(poll_calls) < 2:
                r.json.return_value = {"data": {"status": "PROCESSING"}}
            else:
                r.json.return_value = {
                    "data": {
                        "status": "SUCCESS",
                        "output_videos": [{"url": "https://cdn/result.mp4"}],
                    }
                }
        else:
            # 動画 DL
            r.content = b"FINAL_VIDEO_BYTES"
        return r

    monkeypatch.setattr(lipsync_client.requests, "post", fake_post)
    monkeypatch.setattr(lipsync_client.requests, "put", fake_put)
    monkeypatch.setattr(lipsync_client.requests, "get", fake_get)

    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.m4a"
    out = tmp_path / "out.mp4"
    video.write_bytes(b"V")
    audio.write_bytes(b"A")

    lipsync_client._apply_domoai_sync(str(video), str(audio), str(out))

    assert out.read_bytes() == b"FINAL_VIDEO_BYTES"

    # upload (×2) + create task (×1) の3 POST
    posts = [c for c in calls if c[0] == "POST"]
    assert sum(1 for _, u, _ in posts if u.endswith("/upload/file")) == 2
    create = [c for c in posts if c[2].get("seconds") is not None]
    assert len(create) == 1
    body = create[0][2]
    assert body["seconds"] == 5  # ceil(4.7) = 5
    assert body["model"] == "talking-avatar-v1"
    assert body["video"]["domoai_uri"].startswith("jwt-for-v.mp4")
    assert body["audio"]["domoai_uri"].startswith("jwt-for-a.m4a")
    assert len(poll_calls) == 2  # PROCESSING → SUCCESS


def test_apply_domoai_sync_raises_on_failed_status(tmp_path, monkeypatch) -> None:
    _stub_domoai_env(monkeypatch)
    monkeypatch.setattr(lipsync_client, "_ffprobe_duration", lambda p: 3.0)

    def fake_post(url, **kw):
        r = MagicMock()
        r.status_code = 200
        if url.endswith("/upload/file"):
            r.json.return_value = {
                "data": {
                    "presigned_url": "https://s3/x",
                    "headers": {},
                    "domoai_uri": "uri",
                }
            }
        else:
            r.json.return_value = {"data": {"task_id": "t1"}}
        return r

    def fake_put(url, **kw):
        r = MagicMock(); r.status_code = 200; return r

    def fake_get(url, **kw):
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status.return_value = None
        r.json.return_value = {
            "data": {"status": "FAILED", "error": "bad input"}
        }
        return r

    monkeypatch.setattr(lipsync_client.requests, "post", fake_post)
    monkeypatch.setattr(lipsync_client.requests, "put", fake_put)
    monkeypatch.setattr(lipsync_client.requests, "get", fake_get)

    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.m4a"
    video.write_bytes(b"V")
    audio.write_bytes(b"A")

    with pytest.raises(lipsync_client.LipsyncClientError) as exc:
        lipsync_client._apply_domoai_sync(
            str(video), str(audio), str(tmp_path / "o.mp4"))
    assert "FAILED" in str(exc.value)


# ─────────────────────── Sync.so provider ───────────────────────


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


def test_apply_dispatches_to_syncso(monkeypatch) -> None:
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "syncso")
    mock_handler = MagicMock()
    monkeypatch.setitem(lipsync_client._PROVIDERS, "syncso", mock_handler)

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


def test_apply_domoai_sync_raises_on_long_audio(tmp_path, monkeypatch) -> None:
    """音声が 60s を超える場合は clamp せず LipsyncClientError を raise (= API 呼ばない)。"""
    _stub_domoai_env(monkeypatch)
    monkeypatch.setattr(lipsync_client, "_ffprobe_duration", lambda p: 65.0)

    post_calls: list[str] = []
    put_calls: list[str] = []

    def fake_post(url, **_):
        post_calls.append(url)
        r = MagicMock(); r.status_code = 200
        return r

    def fake_put(url, **_):
        put_calls.append(url)
        r = MagicMock(); r.status_code = 200
        return r

    monkeypatch.setattr(lipsync_client.requests, "post", fake_post)
    monkeypatch.setattr(lipsync_client.requests, "put", fake_put)

    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.m4a"
    video.write_bytes(b"V"); audio.write_bytes(b"A")

    with pytest.raises(lipsync_client.LipsyncClientError) as exc:
        lipsync_client._apply_domoai_sync(
            str(video), str(audio), str(tmp_path / "o.mp4"))
    msg = str(exc.value)
    assert "上限" in msg
    assert "超過" in msg
    assert "65.0" in msg
    assert post_calls == []
    assert put_calls == []


def test_apply_domoai_sync_processes_short_audio(tmp_path, monkeypatch) -> None:
    """30s 程度の音声は通常通り seconds=30 で送信される。"""
    _stub_domoai_env(monkeypatch)
    monkeypatch.setattr(lipsync_client, "_ffprobe_duration", lambda p: 30.0)

    create_payload: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        r = MagicMock(); r.status_code = 200
        if url.endswith("/upload/file"):
            r.json.return_value = {
                "data": {
                    "presigned_url": "https://s3/x",
                    "headers": {},
                    "domoai_uri": "uri",
                }
            }
        else:
            create_payload.update(json or {})
            r.json.return_value = {"data": {"task_id": "t1"}}
        return r

    def fake_put(url, **kw):
        r = MagicMock(); r.status_code = 200; return r

    def fake_get(url, **kw):
        r = MagicMock(); r.status_code = 200
        r.raise_for_status.return_value = None
        if "/tasks/" in url:
            r.json.return_value = {
                "data": {
                    "status": "SUCCESS",
                    "output_videos": [{"url": "https://cdn/x.mp4"}],
                }
            }
        else:
            r.content = b"X"
        return r

    monkeypatch.setattr(lipsync_client.requests, "post", fake_post)
    monkeypatch.setattr(lipsync_client.requests, "put", fake_put)
    monkeypatch.setattr(lipsync_client.requests, "get", fake_get)

    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.m4a"
    video.write_bytes(b"V"); audio.write_bytes(b"A")

    lipsync_client._apply_domoai_sync(
        str(video), str(audio), str(tmp_path / "o.mp4"))

    assert create_payload["seconds"] == 30
