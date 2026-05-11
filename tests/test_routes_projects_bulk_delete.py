"""POST /api/projects/bulk-delete の API テスト。

設計 doc: docs/plannings/2026-05-11_delete-projects-ui.md §4 Phase A
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
    started: list[str] = []
    from analyze import runner as analyze_runner
    monkeypatch.setattr(
        analyze_runner, "start",
        lambda jid: (started.append(jid), None)[1],
    )
    return started


@pytest.fixture
def cancel_requests(monkeypatch):
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


def _create_project(client, suffix: str = "ref") -> str:
    """from-reference-video 経由で project 1 つ作成、ts を返す。
    suffix を変えると別 sha が付くので複数 project 作成に使える。
    """
    data = {"reference_video": (io.BytesIO(f"\x00bytes_{suffix}".encode()), f"{suffix}.mp4")}
    r = client.post(
        "/api/projects/from-reference-video",
        data=data, content_type="multipart/form-data",
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()["ts"]


def _mkdir_project(temp_dir, ts: str) -> str:
    """temp/<ts>/ ディレクトリだけを直接作る (= TS 衝突回避用)。
    bulk-delete の挙動は dir の有無だけで決まるので、analyze_job linkage は
    test 対象ではない。
    """
    p = temp_dir / ts
    p.mkdir(parents=True, exist_ok=True)
    # 最低限の metadata.json を置く (= read_metadata が None を返すと job 経路へ
    # 入らないので OK だが、明示的に空 dict で書いておく)
    (p / "metadata.json").write_text("{}", encoding="utf-8")
    return ts


# ─── happy path ─────────────────────────────────────


def test_bulk_delete_deletes_all_when_valid(
    client, isolated_env, runner_started_jobs,
) -> None:
    # 同秒内に 3 件作ると TS が衝突するので、_mkdir_project で直接作る
    ts1 = _mkdir_project(isolated_env["temp_dir"], "20260511_220521")
    ts2 = _mkdir_project(isolated_env["temp_dir"], "20260511_220522")
    ts3 = _mkdir_project(isolated_env["temp_dir"], "20260511_220523")

    r = client.post(
        "/api/projects/bulk-delete",
        json={"ts_list": [ts1, ts2, ts3]},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert set(body["deleted"]) == {ts1, ts2, ts3}
    assert body["failed"] == []

    # ディレクトリが全部消えている
    for ts in (ts1, ts2, ts3):
        assert not (isolated_env["temp_dir"] / ts).exists()


def test_bulk_delete_partial_success_collects_missing_in_failed(
    client, isolated_env, runner_started_jobs,
) -> None:
    """1 つだけ実在、残りは PROJECT_NOT_FOUND を failed に記録、existing は削除。"""
    ts_real = _mkdir_project(isolated_env["temp_dir"], "20260511_220521")

    r = client.post(
        "/api/projects/bulk-delete",
        json={"ts_list": [ts_real, "99999999_999999", "20260101_120000"]},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["deleted"] == [ts_real]
    fails = {f["ts"]: f for f in body["failed"]}
    assert "99999999_999999" in fails
    assert fails["99999999_999999"]["error_code"] == "PROJECT_NOT_FOUND"
    assert "20260101_120000" in fails
    assert fails["20260101_120000"]["error_code"] == "PROJECT_NOT_FOUND"


def test_bulk_delete_invalid_ts_collected_individually(
    client, isolated_env, runner_started_jobs,
) -> None:
    """ts format 違反は INVALID_TS で failed、残りは処理続行。"""
    ts = _mkdir_project(isolated_env["temp_dir"], "20260511_220521")
    r = client.post(
        "/api/projects/bulk-delete",
        json={"ts_list": [ts, "../etc/passwd", "<script>"]},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["deleted"] == [ts]
    codes = {f["ts"]: f["error_code"] for f in body["failed"]}
    assert codes["../etc/passwd"] == "INVALID_TS"
    assert codes["<script>"] == "INVALID_TS"


def test_bulk_delete_cancels_in_flight_jobs(
    client, isolated_env, runner_started_jobs, cancel_requests,
) -> None:
    """analyze 実行中の project を bulk delete すると cancel が走る。
    1 件のみ create_project で実 job を作り、もう 1 件は dir のみ (cancel 対象外)
    にしておく (= TS 衝突を避ける)。
    """
    from analyze import job as analyze_job
    ts1 = _create_project(client, "a")

    import staged_pipeline
    meta1 = staged_pipeline.read_metadata(str(isolated_env["temp_dir"] / ts1)) or {}
    analyze_job.transition_status(meta1["analyze_job_id"], "running")

    # 別 TS の project (job 紐付け無し)
    ts2 = _mkdir_project(isolated_env["temp_dir"], "20300101_010101")

    r = client.post(
        "/api/projects/bulk-delete",
        json={"ts_list": [ts1, ts2]},
    )
    assert r.status_code == 200
    assert set(r.get_json()["deleted"]) == {ts1, ts2}
    # ts1 だけ cancel された (= ts2 は metadata.analyze_job_id が無いのでスキップ)
    assert cancel_requests == [meta1["analyze_job_id"]]


# ─── validation errors ─────────────────────────────


def test_bulk_delete_400_when_ts_list_missing(client) -> None:
    r = client.post("/api/projects/bulk-delete", json={})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "BULK_DELETE_INVALID_LIST"


def test_bulk_delete_400_when_ts_list_not_a_list(client) -> None:
    r = client.post("/api/projects/bulk-delete", json={"ts_list": "not-a-list"})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "BULK_DELETE_INVALID_LIST"


def test_bulk_delete_400_when_empty_list(client) -> None:
    r = client.post("/api/projects/bulk-delete", json={"ts_list": []})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "BULK_DELETE_EMPTY_LIST"


def test_bulk_delete_400_when_too_many(client) -> None:
    r = client.post(
        "/api/projects/bulk-delete",
        json={"ts_list": [f"20260101_{i:06d}" for i in range(101)]},
    )
    assert r.status_code == 400
    body = r.get_json()
    assert body["error_code"] == "BULK_DELETE_TOO_MANY"
    assert body["limit"] == 100
    assert body["given"] == 101


def test_bulk_delete_preserves_reference_videos(
    client, isolated_env, runner_started_jobs,
) -> None:
    """bulk delete でも reference_videos/ は消えない (= 既存 single-delete と同じ不変条件)。"""
    ts1 = _create_project(client, "a")
    ref_files_before = list(isolated_env["ref_dir"].iterdir())
    assert len(ref_files_before) >= 1

    r = client.post(
        "/api/projects/bulk-delete",
        json={"ts_list": [ts1]},
    )
    assert r.status_code == 200
    # reference_videos は残っている
    ref_files_after = list(isolated_env["ref_dir"].iterdir())
    assert set(ref_files_after) == set(ref_files_before)
