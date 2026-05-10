"""GET / DELETE / POST :id/confirm / :id/events の API テスト。

POST /api/screenplay/analyze (= 旧 standalone create) と
GET /api/screenplay/analyze (= 旧 standalone list) は Phase E で削除済み。
残っている item-level handler (= AnalyzeStage0Page → AnalyzeJobView 経由で
使う) のみを検証する。

実際の analyze pipeline は呼ばずに analyze.runner.start を mock で差し替え、
ジョブ管理 API の挙動だけを検証する。
"""
import io

import pytest


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    ref_dir = tmp_path / "reference_videos"
    ref_dir.mkdir()

    from analytics import db as _db
    _db.init_db()

    from analyze import job as analyze_job
    monkeypatch.setattr(analyze_job, "REFERENCE_VIDEOS_DIR", ref_dir)
    return {"ref_dir": ref_dir}


@pytest.fixture
def client(isolated_env, monkeypatch):
    import preview_server
    preview_server.app.config["TESTING"] = True
    monkeypatch.setattr(preview_server, "_ffprobe_duration", lambda p: 5.0)
    # runner.start を no-op に (実 thread を起動しない)
    started: list[str] = []
    monkeypatch.setattr(preview_server.analyze_runner, "start",
                         lambda job_id: started.append(job_id) or None)
    preview_server._test_started_jobs = started
    return preview_server.app.test_client()


def _upload(client, name="ref.mov", body=b"\x00data") -> str:
    r = client.post("/api/reference_videos",
                    data={"file": (io.BytesIO(body), name)},
                    content_type="multipart/form-data")
    assert r.status_code in (200, 201)
    return r.get_json()["sha256"]


def _create_job(client) -> str:
    """analyze_job.create_job を直接叩いて job_id を返す。

    Phase E で POST /api/screenplay/analyze が削除されたため、test 用 setup
    としてはモジュール直接呼びにする (= 本番 path は POST
    /api/projects/from-reference-video が `create_job(..., project_ts=ts)` を
    内部で呼ぶ)。
    """
    from analyze import job as analyze_job
    sha = _upload(client)
    return analyze_job.create_job(sha, {}).id


def test_get_job_includes_phases(client) -> None:
    job_id = _create_job(client)
    r = client.get(f"/api/screenplay/analyze/{job_id}")
    body = r.get_json()
    assert body["status"] == "pending"
    assert isinstance(body["phases"], list)
    assert {p["phase"] for p in body["phases"]} >= {
        "frames", "audio", "whisper", "claude", "save",
    }


def test_get_job_404_for_unknown(client) -> None:
    r = client.get("/api/screenplay/analyze/analyze_unknown")
    assert r.status_code == 404


def test_get_job_400_for_invalid_id(client) -> None:
    r = client.get("/api/screenplay/analyze/bad-id")
    assert r.status_code == 400


def test_confirm_rejects_when_not_awaiting(client) -> None:
    job_id = _create_job(client)
    r = client.post(f"/api/screenplay/analyze/{job_id}/confirm")
    assert r.status_code == 409


def test_confirm_succeeds_when_awaiting(client) -> None:
    from analyze import job as analyze_job
    job_id = _create_job(client)
    analyze_job.transition_status(job_id, "awaiting_confirm",
                                    estimated_cost_usd=0.5)
    r = client.post(f"/api/screenplay/analyze/{job_id}/confirm")
    assert r.status_code == 200
    assert analyze_job.get_job(job_id).status == "running"


def test_cancel_sets_flag(client) -> None:
    from analyze import job as analyze_job
    job_id = _create_job(client)
    r = client.delete(f"/api/screenplay/analyze/{job_id}")
    assert r.status_code == 202
    assert analyze_job.is_cancellation_requested(job_id)


def test_events_stream_emits_state_then_published(client) -> None:
    from analyze import progress as analyze_progress
    job_id = _create_job(client)

    # SSE は generator なので一部だけ取り出す。
    rv = client.get(f"/api/screenplay/analyze/{job_id}/events",
                    buffered=False)
    assert rv.status_code == 200
    assert rv.mimetype == "text/event-stream"

    iterator = rv.iter_encoded()
    first = next(iterator).decode("utf-8")
    assert first.startswith("event: state\n")
    assert '"status": "pending"' in first

    analyze_progress.publish(job_id, "phase_start", {"phase": "frames"})
    second = next(iterator).decode("utf-8")
    assert second.startswith("event: phase_start\n")

    analyze_progress.publish(job_id, "completed", {"output": "x"})
    third = next(iterator).decode("utf-8")
    assert third.startswith("event: completed\n")
    rv.close()
    analyze_progress.clear_subscribers(job_id)


def test_events_stream_terminates_immediately_for_finished_job(client) -> None:
    """既に completed のジョブは subscribe せず state event だけ返して終了する。"""
    from analyze import job as analyze_job
    job_id = _create_job(client)
    analyze_job.transition_status(job_id, "completed",
                                    screenplay_path="/tmp/x.json")

    rv = client.get(f"/api/screenplay/analyze/{job_id}/events")
    body = rv.get_data(as_text=True)
    assert "event: state" in body
    assert '"status": "completed"' in body
