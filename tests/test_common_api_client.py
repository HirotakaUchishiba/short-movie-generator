"""common/api_client.py の単体テスト。

APIClientError の属性 / 既存 ClientError との継承関係 / call_with_retry の
正常系 / 例外分類 / 上限超過を確認する。
"""

import pytest

from common.api_client import APIClientError, call_with_retry


def test_api_client_error_default_attributes():
    err = APIClientError("boom")
    assert str(err) == "boom"
    assert err.status is None
    assert err.retryable is False


def test_api_client_error_carries_status_and_retryable():
    err = APIClientError("rate limited", status=429, retryable=True)
    assert err.status == 429
    assert err.retryable is True


def test_existing_client_errors_subclass_api_client_error():
    import elevenlabs_client
    import fal_video_client
    import lipsync_client

    assert issubclass(elevenlabs_client.ElevenLabsClientError, APIClientError)
    assert issubclass(fal_video_client.FalClientError, APIClientError)
    assert issubclass(lipsync_client.LipsyncClientError, APIClientError)


def test_call_with_retry_returns_first_success():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = call_with_retry(
        fn, max_retries=3, backoff_seconds=[0.1],
        sleep=lambda _: None,
    )
    assert result == "ok"
    assert len(calls) == 1


def test_call_with_retry_retries_on_exception_then_succeeds():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("transient")
        return "ok"

    result = call_with_retry(
        fn, max_retries=5, backoff_seconds=[0.1, 0.2, 0.4],
        sleep=lambda _: None,
    )
    assert result == "ok"
    assert len(calls) == 3


def test_call_with_retry_max_retries_exhausted_raises_last_exception():
    calls = []

    def fn():
        calls.append(1)
        raise RuntimeError(f"fail{len(calls)}")

    with pytest.raises(RuntimeError, match="fail3"):
        call_with_retry(
            fn, max_retries=3, backoff_seconds=[0.1],
            sleep=lambda _: None,
        )
    assert len(calls) == 3


def test_call_with_retry_classify_fail_raises_immediately():
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("validation error")

    def classify(exc):
        return "fail" if isinstance(exc, ValueError) else "retry"

    with pytest.raises(ValueError):
        call_with_retry(
            fn, max_retries=5, backoff_seconds=[0.1],
            classify=classify,
            sleep=lambda _: None,
        )
    assert len(calls) == 1  # 即座に raise、retry なし


def test_call_with_retry_backoff_schedule_repeats_last_value():
    """backoff_seconds が max_retries より短ければ末尾値を流用。"""
    waits: list[float] = []
    calls = []

    def fn():
        calls.append(1)
        raise RuntimeError("transient")

    with pytest.raises(RuntimeError):
        call_with_retry(
            fn, max_retries=5, backoff_seconds=[1.0, 2.0],  # 2 個だけ
            sleep=lambda s: waits.append(s),
        )
    # attempt 0 失敗後: backoff[0]=1.0
    # attempt 1 失敗後: backoff[1]=2.0
    # attempt 2-3 失敗後: backoff[-1]=2.0 (clamp)
    assert waits == [1.0, 2.0, 2.0, 2.0]
