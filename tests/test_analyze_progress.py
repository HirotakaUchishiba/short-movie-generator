"""analyze.progress の単体テスト (publish/subscribe)。"""
import threading
import time

import pytest

from analyze import progress


@pytest.fixture(autouse=True)
def _clear_subs():
    """各テスト後に subscriber を全部解除する。"""
    yield
    progress.clear_subscribers()


def test_publish_to_no_subscriber_is_noop() -> None:
    progress.publish("nojob", "x", {"a": 1})


def test_subscriber_receives_published_event() -> None:
    received: list = []

    def sub_thread():
        for event, data in progress.subscribe("job1", heartbeat_sec=0.5):
            received.append((event, data))
            if event == "completed":
                break

    t = threading.Thread(target=sub_thread, daemon=True)
    t.start()
    time.sleep(0.05)
    progress.publish("job1", "phase_start", {"phase": "frames"})
    progress.publish("job1", "completed", {"output": "x"})
    t.join(timeout=2.0)

    assert ("phase_start", {"phase": "frames"}) in received
    assert ("completed", {"output": "x"}) in received


def test_multiple_subscribers_each_receive_event() -> None:
    received1: list = []
    received2: list = []

    def make_sub(out: list):
        def f():
            for event, data in progress.subscribe("job_multi", heartbeat_sec=0.3):
                out.append((event, data))
                if event == "completed":
                    break
        return f

    t1 = threading.Thread(target=make_sub(received1), daemon=True)
    t2 = threading.Thread(target=make_sub(received2), daemon=True)
    t1.start()
    t2.start()
    time.sleep(0.05)
    assert progress.subscriber_count("job_multi") == 2

    progress.publish("job_multi", "completed", {})
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert received1 == [("completed", {})]
    assert received2 == [("completed", {})]


def test_heartbeat_keeps_connection_alive() -> None:
    received: list = []
    stop = threading.Event()

    def sub():
        for event, data in progress.subscribe("job_hb", heartbeat_sec=0.05):
            received.append((event, data))
            if stop.is_set():
                break

    t = threading.Thread(target=sub, daemon=True)
    t.start()
    time.sleep(0.2)  # heartbeat が複数回出るのを待つ
    stop.set()
    progress.publish("job_hb", "completed", {})
    t.join(timeout=1.0)

    heartbeats = [e for e in received if e[0] == "heartbeat"]
    assert len(heartbeats) >= 1


def test_subscriber_cleaned_up_on_exit() -> None:
    def sub():
        gen = progress.subscribe("job_cleanup", heartbeat_sec=0.05)
        next(gen)  # heartbeat 一回もらって終わる
        gen.close()

    t = threading.Thread(target=sub, daemon=True)
    t.start()
    t.join(timeout=1.0)
    assert progress.subscriber_count("job_cleanup") == 0
