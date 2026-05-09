"""per-TS の並行 job 起動ガードのテスト (_spawn_job exclusive_ts)。"""

import threading
import time

import pytest

import preview_server
from preview_server import JobAlreadyRunningError


@pytest.fixture(autouse=True)
def _clear_jobs():
    """各テスト前に内部 state をクリア。"""
    with preview_server._jobs_lock:
        preview_server._jobs.clear()
        preview_server._active_ts.clear()
    yield
    with preview_server._jobs_lock:
        preview_server._jobs.clear()
        preview_server._active_ts.clear()


def test_spawn_job_exclusive_blocks_second_spawn():
    """同 ts に対する 2 回目の spawn (exclusive_ts=True) は raise する。"""
    barrier = threading.Event()

    def slow():
        barrier.wait(timeout=2)

    job_a = preview_server._spawn_job(slow, kind="run-next", ts="ts1")
    assert job_a in preview_server._jobs

    with pytest.raises(JobAlreadyRunningError) as ei:
        preview_server._spawn_job(slow, kind="run-next", ts="ts1")
    assert ei.value.ts == "ts1"
    assert ei.value.existing_job_id == job_a

    barrier.set()  # 1 つ目を完了させる
    # runner が completed になるまで待つ
    for _ in range(20):
        with preview_server._jobs_lock:
            if preview_server._jobs[job_a]["status"] == "completed":
                break
        time.sleep(0.05)


def test_spawn_job_allows_after_completion():
    """1 つ目が完了したあとは同 ts でも spawn できる。"""
    def quick():
        return None

    job_a = preview_server._spawn_job(quick, kind="run-next", ts="ts2")
    for _ in range(20):
        with preview_server._jobs_lock:
            if preview_server._jobs[job_a]["status"] == "completed":
                break
        time.sleep(0.05)

    job_b = preview_server._spawn_job(quick, kind="run-next", ts="ts2")
    assert job_b != job_a


def test_spawn_job_allows_after_failure():
    """1 つ目が failed になったあとは同 ts でも spawn できる。"""
    def boom():
        raise RuntimeError("boom")

    job_a = preview_server._spawn_job(boom, kind="run-next", ts="ts3")
    for _ in range(20):
        with preview_server._jobs_lock:
            if preview_server._jobs[job_a]["status"] == "failed":
                break
        time.sleep(0.05)

    def quick():
        return None
    job_b = preview_server._spawn_job(quick, kind="run-next", ts="ts3")
    assert job_b != job_a


def test_spawn_job_different_ts_allowed_in_parallel():
    """別 ts は並行に走れる (= 同時実行を不必要に制限しない)。"""
    barrier = threading.Event()

    def slow():
        barrier.wait(timeout=2)

    job_a = preview_server._spawn_job(slow, kind="run-next", ts="tsA")
    job_b = preview_server._spawn_job(slow, kind="run-next", ts="tsB")
    assert job_a != job_b
    barrier.set()


def test_spawn_job_exclusive_false_does_not_block():
    """exclusive_ts=False (= read-only ジョブ等) は並行に許す。"""
    barrier = threading.Event()

    def slow():
        barrier.wait(timeout=2)

    preview_server._spawn_job(slow, kind="meta-fetch", ts="ts4")
    # exclusive_ts=False を渡せば 2 回目も走る
    preview_server._spawn_job(slow, kind="meta-fetch", ts="ts4",
                                  exclusive_ts=False)
    barrier.set()


def test_run_next_returns_409_when_already_running(monkeypatch, tmp_path):
    """API: 同 ts に対する 2 回目の run-next POST が 409 を返す。"""
    import config
    import progress_store
    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr(preview_server, "TEMP_DIR", str(tmp_path / "temp"))

    ts = "20260507_120000"
    ts_path = tmp_path / "temp" / ts
    ts_path.mkdir(parents=True)
    progress_store.mark_generated(str(ts_path), "script")

    barrier = threading.Event()

    def slow_runner(*_a, **_kw):
        barrier.wait(timeout=2)
        return "tts"

    monkeypatch.setattr("staged_pipeline.run_next_stage", slow_runner)
    # routes/stages.py が `from routes._helpers import load_screenplay_for_project`
    # しているので、import サイト (= routes.stages) で monkeypatch する。
    import routes.stages
    monkeypatch.setattr(
        routes.stages, "load_screenplay_for_project",
        lambda ts, *, temp_dir=None: (
            {"caption": "c", "scenes": []}, "demo.json",
        ),
    )

    preview_server.app.config["TESTING"] = True
    client = preview_server.app.test_client()

    r1 = client.post(f"/api/projects/{ts}/run-next")
    assert r1.status_code == 200, r1.get_json()
    j = r1.get_json()
    assert "job_id" in j

    r2 = client.post(f"/api/projects/{ts}/run-next")
    assert r2.status_code == 409, r2.get_json()
    payload = r2.get_json()
    assert payload["ts"] == ts
    assert payload["existing_job_id"] == j["job_id"]
    barrier.set()
