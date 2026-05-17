from unittest.mock import MagicMock

import pytest
import requests

import elevenlabs_client


def test_credit_multiplier_known_models() -> None:
    assert elevenlabs_client.credit_multiplier("eleven_v3") == 2.0
    assert elevenlabs_client.credit_multiplier("eleven_multilingual_v2") == 1.0
    assert elevenlabs_client.credit_multiplier("eleven_turbo_v2_5") == 0.5
    assert elevenlabs_client.credit_multiplier("eleven_flash_v2_5") == 0.33


def test_credit_multiplier_unknown_falls_back_to_one() -> None:
    assert elevenlabs_client.credit_multiplier("eleven_xyz_unknown") == 1.0


def test_credit_multiplier_uses_module_default(monkeypatch) -> None:
    monkeypatch.setattr(elevenlabs_client, "MODEL_ID", "eleven_v3")
    assert elevenlabs_client.credit_multiplier() == 2.0
    monkeypatch.setattr(elevenlabs_client, "MODEL_ID", "eleven_multilingual_v2")
    assert elevenlabs_client.credit_multiplier() == 1.0


def test_models_without_context_set() -> None:
    assert "eleven_v3" in elevenlabs_client.MODELS_WITHOUT_CONTEXT
    assert "eleven_multilingual_v2" not in elevenlabs_client.MODELS_WITHOUT_CONTEXT


def _ok_response():
    r = MagicMock(spec=requests.Response)
    r.ok = True
    r.status_code = 200
    return r


def _err_response(status: int, body: str = "", retry_after: str | None = None):
    r = MagicMock(spec=requests.Response)
    r.ok = False
    r.status_code = status
    r.text = body
    r.headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return r


def test_classify_status_5xx_retries():
    assert elevenlabs_client._classify_status(503, "") == "retry"
    assert elevenlabs_client._classify_status(500, "") == "retry"


def test_classify_status_429_retries():
    assert elevenlabs_client._classify_status(429, "rate limit") == "retry"


def test_classify_status_4xx_fails():
    assert elevenlabs_client._classify_status(400, "bad input") == "fail"
    assert elevenlabs_client._classify_status(401, "unauthorized") == "fail"
    assert elevenlabs_client._classify_status(422, "validation") == "fail"


def test_classify_status_credit_exhaustion_fails_even_on_5xx_body():
    assert elevenlabs_client._classify_status(503, "exhausted balance") == "fail"
    assert elevenlabs_client._classify_status(500, "out of credits") == "fail"


def test_post_with_retry_returns_first_success(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _ok_response()

    monkeypatch.setattr(elevenlabs_client.requests, "post", fake_post)
    resp = elevenlabs_client._post_with_retry("u", {}, {})
    assert resp.ok
    assert len(calls) == 1


def test_post_with_retry_retries_on_5xx_then_succeeds(monkeypatch):
    sequence = [_err_response(503, "boom"), _err_response(503, "boom"),
                _ok_response()]
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return sequence.pop(0)

    monkeypatch.setattr(elevenlabs_client.requests, "post", fake_post)
    monkeypatch.setattr(elevenlabs_client.time, "sleep", lambda _s: None)
    resp = elevenlabs_client._post_with_retry("u", {}, {})
    assert resp.ok
    assert len(calls) == 3


def test_post_with_retry_honors_retry_after_header(monkeypatch):
    """429 with Retry-After ヘッダ → そのヘッダ値で待つ。"""
    sequence = [_err_response(429, "rate limit", retry_after="2"),
                _ok_response()]
    sleep_calls: list[float] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        return sequence.pop(0)

    monkeypatch.setattr(elevenlabs_client.requests, "post", fake_post)
    monkeypatch.setattr(elevenlabs_client.time, "sleep",
                        lambda s: sleep_calls.append(s))
    monkeypatch.setattr(elevenlabs_client.io_utils.random,
                        "uniform", lambda _a, _b: 0.0)  # disable jitter
    resp = elevenlabs_client._post_with_retry("u", {}, {})
    assert resp.ok
    assert sleep_calls == [2.0]  # Retry-After=2 を使用


def test_post_with_retry_fails_immediately_on_4xx(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _err_response(401, "unauthorized")

    monkeypatch.setattr(elevenlabs_client.requests, "post", fake_post)
    monkeypatch.setattr(elevenlabs_client.time, "sleep", lambda _s: None)
    with pytest.raises(elevenlabs_client.ElevenLabsClientError) as exc:
        elevenlabs_client._post_with_retry("u", {}, {})
    assert "401" in str(exc.value)
    assert len(calls) == 1


def test_post_with_retry_fails_immediately_on_credit_exhaustion(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _err_response(503, "exhausted balance: please top up")

    monkeypatch.setattr(elevenlabs_client.requests, "post", fake_post)
    monkeypatch.setattr(elevenlabs_client.time, "sleep", lambda _s: None)
    with pytest.raises(elevenlabs_client.ElevenLabsClientError):
        elevenlabs_client._post_with_retry("u", {}, {})
    assert len(calls) == 1


def test_post_with_retry_retries_on_connection_error(monkeypatch):
    sequence = [requests.ConnectionError("boom"), _ok_response()]
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        nxt = sequence.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr(elevenlabs_client.requests, "post", fake_post)
    monkeypatch.setattr(elevenlabs_client.time, "sleep", lambda _s: None)
    resp = elevenlabs_client._post_with_retry("u", {}, {})
    assert resp.ok
    assert len(calls) == 2


def test_post_with_retry_max_retries_exhausted(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _err_response(503, "boom")

    monkeypatch.setattr(elevenlabs_client.requests, "post", fake_post)
    monkeypatch.setattr(elevenlabs_client.time, "sleep", lambda _s: None)
    with pytest.raises(elevenlabs_client.ElevenLabsClientError):
        elevenlabs_client._post_with_retry("u", {}, {})
    assert len(calls) == elevenlabs_client.MAX_RETRIES


def test_parse_eleven_response_malformed_json_raises_client_error():
    r = MagicMock(spec=requests.Response)
    r.status_code = 200
    r.json.side_effect = ValueError("Expecting value")
    with pytest.raises(elevenlabs_client.ElevenLabsClientError) as exc:
        elevenlabs_client._parse_eleven_response(r, context="tts")
    assert "JSON parse" in str(exc.value)


def test_parse_eleven_response_non_dict_raises_client_error():
    r = MagicMock(spec=requests.Response)
    r.status_code = 200
    r.json.return_value = ["not", "a", "dict"]
    with pytest.raises(elevenlabs_client.ElevenLabsClientError) as exc:
        elevenlabs_client._parse_eleven_response(r, context="tts")
    assert "dict ではない" in str(exc.value)


def test_parse_eleven_response_dict_passes_through():
    r = MagicMock(spec=requests.Response)
    r.status_code = 200
    r.json.return_value = {"audio_base64": "aGVsbG8=", "alignment": {}}
    body = elevenlabs_client._parse_eleven_response(r, context="tts")
    assert body["audio_base64"] == "aGVsbG8="


def test_generate_speech_missing_audio_base64_raises(monkeypatch, tmp_path):
    """応答に audio_base64 が無い → ElevenLabsClientError。"""
    def fake_post(url, headers=None, json=None, timeout=None):
        r = MagicMock(spec=requests.Response)
        r.ok = True
        r.status_code = 200
        r.json.return_value = {"alignment": {}}  # audio_base64 欠落
        return r

    monkeypatch.setattr(elevenlabs_client.requests, "post", fake_post)
    monkeypatch.setattr(elevenlabs_client.config, "ELEVENLABS_API_KEY", "k")

    out = tmp_path / "out.mp3"
    with pytest.raises(elevenlabs_client.ElevenLabsClientError) as exc:
        elevenlabs_client.generate_speech_with_timestamps(
            "hello", "voice-id", str(out),
        )
    assert "audio_base64" in str(exc.value)
