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
