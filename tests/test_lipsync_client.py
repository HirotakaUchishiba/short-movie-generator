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
    monkeypatch.setattr(lipsync_client.requests, "get", lambda url: fake_resp)

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


def test_apply_domoai_sync_clamps_long_audio(tmp_path, monkeypatch) -> None:
    """音声が 60s を超える場合は 60s に clamp して送信する (warning ログ付き)。"""
    _stub_domoai_env(monkeypatch)
    monkeypatch.setattr(lipsync_client, "_ffprobe_duration", lambda p: 75.3)

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

    assert create_payload["seconds"] == 60
