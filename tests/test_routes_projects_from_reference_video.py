"""POST /api/projects/from-reference-video の API テスト。

主導フロー (= analyze pipeline を project の Stage 0 として起動) のエントリ。
"""
import io

import pytest


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """テストごとに DB / reference_videos / TEMP_DIR を分離。"""
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
    """analyze_runner.start を no-op に置き換え、起動された job_id を記録する。"""
    started: list[str] = []
    from analyze import runner as analyze_runner

    def fake_start(job_id: str):
        started.append(job_id)
        return None

    monkeypatch.setattr(analyze_runner, "start", fake_start)
    return started


@pytest.fixture
def client(isolated_env, monkeypatch):
    import preview_server
    preview_server.app.config["TESTING"] = True
    # ffprobe を mock (テスト動画には実 metadata が無いので)
    from routes import _helpers as _route_helpers
    monkeypatch.setattr(_route_helpers, "ffprobe_duration", lambda p: 12.5)
    return preview_server.app.test_client()


def _multipart(filename: str, content: bytes, **fields: str) -> dict:
    data: dict = {"reference_video": (io.BytesIO(content), filename)}
    data.update(fields)
    return data


def test_create_returns_ts_and_job_id(client, runner_started_jobs) -> None:
    r = client.post(
        "/api/projects/from-reference-video",
        data=_multipart("ref.mp4", b"\x00fakebytes"),
        content_type="multipart/form-data",
    )
    assert r.status_code == 201
    body = r.get_json()
    assert body["ts"]
    assert body["analyze_job_id"].startswith("analyze_")
    assert body["analyze_job_id"] in runner_started_jobs


def test_create_initializes_metadata_and_progress(
    client, isolated_env, runner_started_jobs,
) -> None:
    r = client.post(
        "/api/projects/from-reference-video",
        data=_multipart("ref.mp4", b"\x00bytes"),
        content_type="multipart/form-data",
    )
    body = r.get_json()
    ts = body["ts"]
    project_path = isolated_env["temp_dir"] / ts

    import staged_pipeline
    meta = staged_pipeline.read_metadata(str(project_path))
    assert meta["analyze_job_id"] == body["analyze_job_id"]
    # Stage 0 中 = screenplay 系 field 不在
    assert "screenplay_name" not in meta

    import progress_store
    assert progress_store.analyze_status(str(project_path)) == "running"


def test_create_persists_options_into_analyze_job(
    client, runner_started_jobs,
) -> None:
    r = client.post(
        "/api/projects/from-reference-video",
        data=_multipart("ref.mp4", b"\x00bytes",
                        instructions="TikTok UI 無視", fps="1.5"),
        content_type="multipart/form-data",
    )
    body = r.get_json()

    from analyze import job as analyze_job
    j = analyze_job.get_job(body["analyze_job_id"])
    assert j.options == {"instructions": "TikTok UI 無視", "fps": 1.5}
    assert j.project_ts == body["ts"]


def test_create_rejects_missing_file(client) -> None:
    r = client.post(
        "/api/projects/from-reference-video",
        data={}, content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "REFERENCE_VIDEO_REQUIRED"


def test_create_rejects_bad_extension(client) -> None:
    r = client.post(
        "/api/projects/from-reference-video",
        data=_multipart("malicious.exe", b"x"),
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    body = r.get_json()
    assert body["error_code"] == "REFERENCE_VIDEO_UNSUPPORTED_EXT"
    assert ".mp4" in body.get("allowed", [])


def test_create_rejects_invalid_fps(client, runner_started_jobs) -> None:
    r = client.post(
        "/api/projects/from-reference-video",
        data=_multipart("ref.mp4", b"\x00bytes", fps="abc"),
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "ANALYZE_INVALID_FPS"


def test_api_projects_includes_analyze_status(
    client, runner_started_jobs,
) -> None:
    """GET /api/projects レスポンスに analyze_status / analyze_job_id が含まれる
    (= ProjectCard の Stage 0 バッジ表示用)。
    """
    body = client.post(
        "/api/projects/from-reference-video",
        data=_multipart("ref.mp4", b"\x00bytes"),
        content_type="multipart/form-data",
    ).get_json()

    r = client.get("/api/projects")
    assert r.status_code == 200
    items = r.get_json()["projects"]
    target = next(p for p in items if p["timestamp"] == body["ts"])
    assert target["analyze_status"] == "running"
    assert target["analyze_job_id"] == body["analyze_job_id"]
    assert target["screenplay_name"] is None  # Stage 0 中


def test_api_project_detail_returns_null_screenplay_during_stage_0(
    client, runner_started_jobs,
) -> None:
    """GET /api/projects/<ts> は Stage 0 中なら screenplay=null + analyze_status を
    返す (= 404 にしない)。AnalyzeStage0Page が読みに来る用。
    """
    body = client.post(
        "/api/projects/from-reference-video",
        data=_multipart("ref.mp4", b"\x00bytes"),
        content_type="multipart/form-data",
    ).get_json()
    r = client.get(f"/api/projects/{body['ts']}")
    assert r.status_code == 200
    detail = r.get_json()
    assert detail["screenplay"] is None
    assert detail["screenplay_name"] is None
    assert detail["analyze_status"] == "running"
    assert detail["analyze_job_id"] == body["analyze_job_id"]


def test_create_dedup_reuses_reference_video(
    client, isolated_env, runner_started_jobs,
) -> None:
    """同じ動画 2 回 POST → ref_video は 1 つ (= dedup)、analyze ジョブは 2 つ。"""
    payload = b"\x00samebytes"
    r1 = client.post(
        "/api/projects/from-reference-video",
        data=_multipart("a.mp4", payload),
        content_type="multipart/form-data",
    )
    r2 = client.post(
        "/api/projects/from-reference-video",
        data=_multipart("b.mp4", payload),
        content_type="multipart/form-data",
    )
    assert r1.status_code == 201 and r2.status_code == 201

    # ref_video は 1 つ (= 同 sha256 は dedup)
    files = list(isolated_env["ref_dir"].glob("*.mp4"))
    assert len(files) == 1

    # 2 つの analyze_job が作られている (= dedup は ref_video のみ、project は別)
    from analyze import job as analyze_job
    jobs = analyze_job.list_jobs()
    assert len(jobs) == 2
