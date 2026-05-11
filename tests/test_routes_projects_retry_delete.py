"""POST /api/projects/<ts>/retry-analyze と DELETE /api/projects/<ts> の API テスト。

設計 §7.1 候補 2 (= 失敗時 project を残し、retry / 削除を選べる) の実装。
"""
import io

import pytest


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    ref_dir = tmp_path / "reference_videos"
    ref_dir.mkdir()
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()

    from analytics import db as _db
    _db.init_db()

    from analyze import job as analyze_job
    monkeypatch.setattr(analyze_job, "REFERENCE_VIDEOS_DIR", ref_dir)

    import config
    monkeypatch.setattr(config, "TEMP_DIR", str(temp_dir))

    return {"ref_dir": ref_dir, "temp_dir": temp_dir}


@pytest.fixture
def runner_started_jobs(monkeypatch):
    """analyze_runner.start を no-op、起動された job_id を記録する。"""
    started: list[str] = []
    from analyze import runner as analyze_runner
    monkeypatch.setattr(
        analyze_runner, "start",
        lambda jid: (started.append(jid), None)[1],
    )
    return started


@pytest.fixture
def cancel_requests(monkeypatch):
    """analyze_runner.cancel をモックして要求を記録する。"""
    cancelled: list[str] = []
    from analyze import runner as analyze_runner
    monkeypatch.setattr(
        analyze_runner, "cancel",
        lambda jid: (cancelled.append(jid), None)[1],
    )
    return cancelled


@pytest.fixture
def client(isolated_env, monkeypatch):
    import preview_server
    preview_server.app.config["TESTING"] = True
    from routes import _helpers as _route_helpers
    monkeypatch.setattr(_route_helpers, "ffprobe_duration", lambda p: 12.5)
    return preview_server.app.test_client()


def _create_project(client, **fields) -> dict:
    """from-reference-video 経由で 1 つ project を作って response を返す。"""
    data: dict = {"reference_video": (io.BytesIO(b"\x00bytes"), "ref.mp4")}
    data.update(fields)
    r = client.post(
        "/api/projects/from-reference-video",
        data=data, content_type="multipart/form-data",
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()


# ─── retry-analyze ─────────────────────────────────────


def test_retry_creates_new_job_when_failed(
    client, isolated_env, runner_started_jobs,
) -> None:
    body = _create_project(client)
    ts = body["ts"]
    project_path = isolated_env["temp_dir"] / ts

    import progress_store
    progress_store.mark_analyze_failed(str(project_path), "claude timeout")

    r = client.post(f"/api/projects/{ts}/retry-analyze")
    assert r.status_code == 200
    new_id = r.get_json()["new_analyze_job_id"]
    assert new_id != body["analyze_job_id"]
    # runner が起動された
    assert new_id in runner_started_jobs
    # progress が running に戻る
    assert progress_store.analyze_status(str(project_path)) == "running"


def test_retry_inherits_video_sha_and_options(
    client, isolated_env, runner_started_jobs,
) -> None:
    body = _create_project(client, fps="1.5")
    ts = body["ts"]
    import progress_store
    progress_store.mark_analyze_failed(
        str(isolated_env["temp_dir"] / ts), "x",
    )
    r = client.post(f"/api/projects/{ts}/retry-analyze")
    new_id = r.get_json()["new_analyze_job_id"]

    from analyze import job as analyze_job
    old = analyze_job.get_job(body["analyze_job_id"])
    new = analyze_job.get_job(new_id)
    assert new.video_sha256 == old.video_sha256
    assert new.options == old.options
    assert new.project_ts == ts


def test_retry_clears_hook_error(
    client, isolated_env, runner_started_jobs,
) -> None:
    body = _create_project(client)
    ts = body["ts"]
    project_path = isolated_env["temp_dir"] / ts

    import progress_store
    import staged_pipeline
    progress_store.mark_analyze_failed(str(project_path), "x")
    # Simulate hook_error left over
    meta = staged_pipeline.read_metadata(str(project_path))
    meta["analyze_hook_error"] = "stale"
    import io_utils
    io_utils.atomic_write_json(str(project_path / "metadata.json"), meta)

    client.post(f"/api/projects/{ts}/retry-analyze")
    meta2 = staged_pipeline.read_metadata(str(project_path))
    assert "analyze_hook_error" not in meta2


def test_retry_rejects_when_running(
    client, isolated_env, runner_started_jobs,
) -> None:
    body = _create_project(client)
    ts = body["ts"]
    # 直後 = analyze_status="running" のまま
    r = client.post(f"/api/projects/{ts}/retry-analyze")
    assert r.status_code == 409
    assert r.get_json()["error_code"] == "ANALYZE_NOT_RETRYABLE"


def test_retry_404_when_project_missing(client) -> None:
    r = client.post("/api/projects/20260101_000000/retry-analyze")
    assert r.status_code == 404
    assert r.get_json()["error_code"] == "PROJECT_NOT_FOUND"


def test_retry_400_when_legacy_project(client, isolated_env) -> None:
    """analyze_job_id 無し (= legacy template 経路) の project は retry 不可。"""
    ts = "20260101_010101"
    project_path = isolated_env["temp_dir"] / ts
    project_path.mkdir()
    import staged_pipeline
    staged_pipeline.write_metadata(
        str(project_path), screenplay_name="manual.json",
        analyze_job_id=None, sha256="aaa",
    )
    r = client.post(f"/api/projects/{ts}/retry-analyze")
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "ANALYZE_JOB_ID_MISSING"


# ─── delete-project ─────────────────────────────────────


def test_delete_removes_project_dir(
    client, isolated_env, runner_started_jobs, cancel_requests,
) -> None:
    body = _create_project(client)
    ts = body["ts"]
    project_path = isolated_env["temp_dir"] / ts
    assert project_path.exists()

    r = client.delete(f"/api/projects/{ts}")
    assert r.status_code == 200
    assert r.get_json() == {"ts": ts, "deleted": True}
    assert not project_path.exists()


def test_delete_cancels_in_flight_job(
    client, isolated_env, runner_started_jobs, cancel_requests,
) -> None:
    body = _create_project(client)  # job is in "pending" status by default
    ts = body["ts"]
    job_id = body["analyze_job_id"]

    client.delete(f"/api/projects/{ts}")
    assert job_id in cancel_requests


def test_delete_keeps_reference_video(
    client, isolated_env, runner_started_jobs, cancel_requests,
) -> None:
    body = _create_project(client)
    ts = body["ts"]
    files_before = list(isolated_env["ref_dir"].glob("*.mp4"))
    assert len(files_before) == 1

    client.delete(f"/api/projects/{ts}")
    files_after = list(isolated_env["ref_dir"].glob("*.mp4"))
    assert files_after == files_before  # ref_video は dedup 用に残す


def test_delete_404_when_project_missing(client) -> None:
    r = client.delete("/api/projects/20260101_000000")
    assert r.status_code == 404
    assert r.get_json()["error_code"] == "PROJECT_NOT_FOUND"


def test_delete_skips_cancel_when_job_completed(
    client, isolated_env, runner_started_jobs, cancel_requests,
) -> None:
    """analyze_job が completed なら cancel は呼ばない (= 不要)。"""
    body = _create_project(client)
    ts = body["ts"]
    job_id = body["analyze_job_id"]

    from analyze import job as analyze_job
    analyze_job.transition_status(job_id, "completed")

    client.delete(f"/api/projects/{ts}")
    assert job_id not in cancel_requests
