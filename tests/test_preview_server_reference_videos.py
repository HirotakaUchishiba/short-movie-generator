"""POST/GET/DELETE /api/reference_videos の API テスト。"""
import io
import os

import pytest


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """テストごとに分離した DB + reference_videos ディレクトリ。"""
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
    # ffprobe を mock (テスト動画には実 metadata が無いので)
    monkeypatch.setattr(preview_server, "_ffprobe_duration", lambda p: 12.5)
    return preview_server.app.test_client()


def _multipart_data(filename: str, content: bytes) -> dict:
    return {"file": (io.BytesIO(content), filename)}


def test_upload_new_video_returns_201(client, isolated_env) -> None:
    r = client.post(
        "/api/reference_videos",
        data=_multipart_data("test.mov", b"\x00\x00fake_video_bytes"),
        content_type="multipart/form-data",
    )
    assert r.status_code == 201
    body = r.get_json()
    assert "sha256" in body and len(body["sha256"]) == 64
    assert body["original_name"] == "test.mov"
    assert body["deduplicated"] is False
    assert body["duration_sec"] == 12.5

    # ファイルが <sha>.mov として保存されている
    saved = isolated_env["ref_dir"] / f"{body['sha256']}.mov"
    assert saved.exists()


def test_upload_duplicate_returns_200_with_dedup(client) -> None:
    payload = b"\x00samebytes"
    r1 = client.post("/api/reference_videos",
                     data=_multipart_data("a.mov", payload),
                     content_type="multipart/form-data")
    assert r1.status_code == 201
    sha1 = r1.get_json()["sha256"]

    r2 = client.post("/api/reference_videos",
                     data=_multipart_data("b.mov", payload),
                     content_type="multipart/form-data")
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["deduplicated"] is True
    assert body["sha256"] == sha1
    # original_name は最初の登録 (a.mov) のまま
    assert body["original_name"] == "a.mov"


def test_upload_rejects_bad_extension(client) -> None:
    r = client.post(
        "/api/reference_videos",
        data=_multipart_data("malicious.exe", b"x"),
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert "unsupported extension" in r.get_json()["error"]


def test_upload_requires_file_field(client) -> None:
    r = client.post("/api/reference_videos",
                    data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_list_returns_uploaded(client) -> None:
    client.post("/api/reference_videos",
                data=_multipart_data("v1.mp4", b"a"),
                content_type="multipart/form-data")
    client.post("/api/reference_videos",
                data=_multipart_data("v2.mov", b"b"),
                content_type="multipart/form-data")

    r = client.get("/api/reference_videos")
    assert r.status_code == 200
    items = r.get_json()["reference_videos"]
    assert len(items) == 2
    assert {it["original_name"] for it in items} == {"v1.mp4", "v2.mov"}


def test_delete_unused_video_succeeds(client, isolated_env) -> None:
    upload = client.post("/api/reference_videos",
                         data=_multipart_data("v.mov", b"x"),
                         content_type="multipart/form-data")
    sha = upload.get_json()["sha256"]

    r = client.delete(f"/api/reference_videos/{sha}")
    assert r.status_code == 200
    assert r.get_json()["deleted"] is True
    assert not (isolated_env["ref_dir"] / f"{sha}.mov").exists()


def test_delete_referenced_video_blocked(client) -> None:
    upload = client.post("/api/reference_videos",
                         data=_multipart_data("v.mov", b"x"),
                         content_type="multipart/form-data")
    sha = upload.get_json()["sha256"]

    # ジョブを作成してこの動画を参照させる
    from analyze import job as analyze_job
    analyze_job.create_job(sha, {})

    r = client.delete(f"/api/reference_videos/{sha}")
    assert r.status_code == 409
    assert "referenced by analyze jobs" in r.get_json()["error"]


def test_delete_invalid_sha_format(client) -> None:
    r = client.delete("/api/reference_videos/not-a-sha")
    assert r.status_code == 400
