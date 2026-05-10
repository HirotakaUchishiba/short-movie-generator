"""Stage 0 (analyze) 中の各 endpoint が ANALYZE_STAGE_NOT_READY (403) を
返すことを確認する。

routes/_helpers.is_analyze_pending を経由した gate が:
- POST /api/projects/<ts>/run-next  (= routes/stages.py)
- POST /api/projects/<ts>/regen     (= routes/stages.py)
- GET  /api/projects/<ts>/abstract  (= preview_server.py)
- PUT  /api/projects/<ts>/abstract  (= preview_server.py)
で動くことを保証する。
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
    # preview_server.TEMP_DIR は import 時に config から copy されるので
    # 明示的に上書き
    import preview_server
    monkeypatch.setattr(preview_server, "TEMP_DIR", str(temp_dir))

    return {"ref_dir": ref_dir, "temp_dir": temp_dir}


@pytest.fixture
def runner_no_op(monkeypatch):
    from analyze import runner as analyze_runner
    monkeypatch.setattr(analyze_runner, "start", lambda jid: None)


@pytest.fixture
def client(isolated_env, monkeypatch, runner_no_op):
    import preview_server
    preview_server.app.config["TESTING"] = True
    from routes import _helpers as _route_helpers
    monkeypatch.setattr(_route_helpers, "ffprobe_duration", lambda p: 12.5)
    return preview_server.app.test_client()


def _create_pending_project(client) -> str:
    """from-reference-video 経由で Stage 0 進行中の project を 1 つ作る。"""
    r = client.post(
        "/api/projects/from-reference-video",
        data={"reference_video": (io.BytesIO(b"\x00bytes"), "ref.mp4")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 201
    return r.get_json()["ts"]


def _expect_403_not_ready(r) -> None:
    assert r.status_code == 403, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "ANALYZE_STAGE_NOT_READY"


def test_run_next_blocked_during_stage_0(client) -> None:
    ts = _create_pending_project(client)
    _expect_403_not_ready(client.post(f"/api/projects/{ts}/run-next"))


def test_regen_blocked_during_stage_0(client) -> None:
    ts = _create_pending_project(client)
    _expect_403_not_ready(
        client.post(
            f"/api/projects/{ts}/regen",
            json={"stage": "tts"},
        ),
    )


def test_abstract_get_blocked_during_stage_0(client) -> None:
    ts = _create_pending_project(client)
    _expect_403_not_ready(client.get(f"/api/projects/{ts}/abstract"))


def test_abstract_put_blocked_during_stage_0(client) -> None:
    ts = _create_pending_project(client)
    _expect_403_not_ready(
        client.put(
            f"/api/projects/{ts}/abstract",
            json={"abstract": {"caption": "x", "scenes": [{}]}},
        ),
    )


def test_failed_analyze_also_blocked(client, isolated_env) -> None:
    """analyze_status=failed も Stage 1+ には進めない (= retry endpoint で別扱い)。"""
    ts = _create_pending_project(client)
    import progress_store
    progress_store.mark_analyze_failed(
        str(isolated_env["temp_dir"] / ts), "claude timeout",
    )
    _expect_403_not_ready(client.post(f"/api/projects/{ts}/run-next"))


def test_endpoints_unblocked_after_analyze_completed(
    client, isolated_env,
) -> None:
    """analyze_status=completed + screenplay snapshot あり → gate を通る。"""
    import shutil

    import progress_store
    import staged_pipeline

    # 1) project 作成 (Stage 0 中)
    ts = _create_pending_project(client)
    project_path = isolated_env["temp_dir"] / ts

    # 2) save phase 完了 hook が走った状態を simulate (= snapshot + metadata + Stage 0/1)
    snap_src = isolated_env["temp_dir"].parent / "auto_demo.json"
    snap_src.write_text(
        '{"caption": "demo", "scenes": [{"animation_prompt": "x",'
        ' "background_prompt": "y", "lines": [{"text": "ok",'
        ' "start": 0.0, "end": 1.0}]}]}',
        encoding="utf-8",
    )
    shutil.copyfile(
        str(snap_src),
        str(project_path / "screenplay.json"),
    )
    staged_pipeline.update_metadata_after_analyze(
        str(project_path), "auto_demo.json", "sha_aaa",
    )
    progress_store.mark_analyze_completed(str(project_path))
    progress_store.mark_generated(str(project_path), "script")
    progress_store.mark_approved(str(project_path), "script")

    # 3) GET abstract が 200 を返す (= もう block されない)
    r = client.get(f"/api/projects/{ts}/abstract")
    assert r.status_code == 200, r.get_data(as_text=True)
