"""fal_runner.run_with_timeout のテスト。"""

import threading
import time

import pytest

from fal_runner import FalJobTimeoutError, run_with_timeout


def test_returns_value_when_fn_completes_in_time() -> None:
    result = run_with_timeout(lambda: 42, timeout_sec=2.0, name="t1")
    assert result == 42


def test_returns_value_for_slow_but_in_time_fn() -> None:
    def slow():
        time.sleep(0.1)
        return "ok"
    result = run_with_timeout(slow, timeout_sec=2.0, name="t2")
    assert result == "ok"


def test_raises_timeout_when_fn_too_slow() -> None:
    def hang():
        time.sleep(5.0)
        return "should never return"

    with pytest.raises(FalJobTimeoutError) as exc:
        run_with_timeout(hang, timeout_sec=0.2, name="hang")
    assert "0s" in str(exc.value) or "0.0s" in str(exc.value)


def test_propagates_exception_from_fn() -> None:
    def boom():
        raise ValueError("explosion")
    with pytest.raises(ValueError, match="explosion"):
        run_with_timeout(boom, timeout_sec=2.0, name="boom")


def test_thread_is_daemon() -> None:
    """生成スレッドが daemon=True であることを確認 (リソースリーク抑止)。"""
    captured: dict = {}

    def fn():
        captured["thread_is_daemon"] = threading.current_thread().daemon
        return None

    run_with_timeout(fn, timeout_sec=2.0, name="check-daemon")
    assert captured["thread_is_daemon"] is True


def test_thread_name_is_set() -> None:
    captured: dict = {}

    def fn():
        captured["name"] = threading.current_thread().name
        return None

    run_with_timeout(fn, timeout_sec=2.0, name="my-job")
    assert "fal-my-job" == captured["name"]


def test_subsequent_calls_independent() -> None:
    """連続呼出で結果が混ざらない。"""
    r1 = run_with_timeout(lambda: 1, timeout_sec=1.0, name="a")
    r2 = run_with_timeout(lambda: 2, timeout_sec=1.0, name="b")
    assert r1 == 1
    assert r2 == 2


def test_fal_job_timeout_is_subclass_of_timeout_error() -> None:
    """既存の except TimeoutError も catch できる。"""
    assert issubclass(FalJobTimeoutError, TimeoutError)


def test_timeout_does_not_block_caller_long_after() -> None:
    """timeout 後に呼出元が即返るか (バックグラウンド thread が daemon で残る)。"""
    start = time.monotonic()
    with pytest.raises(FalJobTimeoutError):
        run_with_timeout(lambda: time.sleep(10), timeout_sec=0.2, name="hang2")
    elapsed = time.monotonic() - start
    # timeout (0.2s) + 余裕 (0.5s) 以内で返るはず
    assert elapsed < 0.7
