"""Stage 8 (final import) と Stage 9 (publish) HTTP routes の単体テスト。"""

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


pytestmark = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg required")


def _make_dummy_mp4(path: Path, duration: float = 1.0) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s=64x64:d={duration}",
        "-f", "lavfi", "-i", f"anullsrc=cl=mono:r=8000:d={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DISABLE_FINAL_WATCHER", "1")
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "ref")

    import preview_server
    import staged_pipeline
    import progress_store
    import config

    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(config, "POST_CAPTIONS_DIR", str(tmp_path / "post_captions"))
    monkeypatch.setattr(preview_server, "TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr(preview_server, "OUTPUT_DIR", str(tmp_path / "output"))
    Path(config.OUTPUT_DIR).mkdir()
    Path(config.POST_CAPTIONS_DIR).mkdir()

    ts = "20260506_160000"
    ts_path = Path(config.TEMP_DIR) / ts
    ts_path.mkdir(parents=True)
    (ts_path / "metadata.json").write_text(json.dumps({
        "screenplay_name": "x.json",
        "screenplay_path": "screenplay.json",
        "screenplay_sha256": "x" * 64,
        "created_at": "2026-05-06T00:00:00",
    }))
    (ts_path / "screenplay.json").write_text(json.dumps({
        "caption": "テスト #tag1",
        "scenes": [{"lines": [{"text": "a"}]}],
    }))
    for s in ["script", "tts", "bg", "kling", "scene", "overlay"]:
        progress_store.mark_generated(str(ts_path), s)
        progress_store.mark_approved(str(ts_path), s)

    cap = Path(config.POST_CAPTIONS_DIR) / "x.md"
    cap.write_text("# x\n\n本文\n#tag1 #tag2\n")

    preview_server.app.config["TESTING"] = True
    return preview_server.app, ts, str(ts_path)


def test_upload_and_list_finals(app, tmp_path):
    flask_app, ts, ts_path = app
    client = flask_app.test_client()

    src = tmp_path / "capcut.mp4"
    _make_dummy_mp4(src, duration=1.5)

    with open(src, "rb") as f:
        r = client.post(
            f"/api/projects/{ts}/final?no_fingerprint=true",
            data={"file": (f, "capcut.mp4")},
            content_type="multipart/form-data",
        )
    assert r.status_code == 201
    body = r.get_json()
    assert body["final_version"]["is_canonical"] is True
    fname = body["final_version"]["filename"]

    r2 = client.get(f"/api/projects/{ts}/final")
    versions = r2.get_json()["final_versions"]
    assert any(v["filename"] == fname for v in versions)

    # asset 配信
    r3 = client.get(f"/asset/{ts}/final-version/{fname}")
    assert r3.status_code == 200
    assert r3.mimetype == "video/mp4"


def test_set_canonical_via_route(app, tmp_path):
    flask_app, ts, ts_path = app
    client = flask_app.test_client()

    for label in ("a.mp4", "b.mp4"):
        p = tmp_path / label
        _make_dummy_mp4(p)
        with open(p, "rb") as f:
            r = client.post(
                f"/api/projects/{ts}/final?no_fingerprint=true",
                data={"file": (f, label)},
                content_type="multipart/form-data",
            )
        assert r.status_code == 201

    versions = client.get(f"/api/projects/{ts}/final").get_json()["final_versions"]
    first = versions[0]["filename"]

    r = client.post(f"/api/projects/{ts}/final/{first}/canonical")
    assert r.status_code == 200
    body = r.get_json()
    assert body["final_version"]["filename"] == first
    assert body["final_version"]["is_canonical"] is True


def test_delete_final_via_route(app, tmp_path):
    flask_app, ts, ts_path = app
    client = flask_app.test_client()

    src = tmp_path / "v.mp4"
    _make_dummy_mp4(src)
    with open(src, "rb") as f:
        r = client.post(
            f"/api/projects/{ts}/final?no_fingerprint=true",
            data={"file": (f, "v.mp4")},
            content_type="multipart/form-data",
        )
    fname = r.get_json()["final_version"]["filename"]

    r2 = client.delete(f"/api/projects/{ts}/final/{fname}")
    assert r2.status_code == 200
    versions = client.get(f"/api/projects/{ts}/final").get_json()["final_versions"]
    assert versions == []


def test_publish_route_returns_job(app, tmp_path, monkeypatch):
    flask_app, ts, ts_path = app
    client = flask_app.test_client()
    import progress_store

    src = tmp_path / "v.mp4"
    _make_dummy_mp4(src)
    with open(src, "rb") as f:
        client.post(
            f"/api/projects/{ts}/final?no_fingerprint=true",
            data={"file": (f, "v.mp4")},
            content_type="multipart/form-data",
        )

    progress_store.mark_approved(ts_path, "final_import")

    class _R:
        status_code = 200
        text = ""
        headers = {"Location": "https://up/"}

        def __init__(self, json_data=None):
            self._j = json_data

        def json(self):
            return self._j

        def raise_for_status(self):
            pass

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _R(json_data={"access_token": "tok"})
        return _R()

    def fake_put(url, **kw):
        r = _R()
        r._j = {"id": "yt_abc"}
        r.status_code = 200
        return r

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    r = client.post(
        f"/api/projects/{ts}/publish",
        json={"platform": "youtube", "privacy": "unlisted"},
    )
    assert r.status_code == 200
    assert r.get_json()["job_id"]


def test_publish_route_rejects_invalid_platform(app):
    flask_app, ts, _ = app
    client = flask_app.test_client()
    r = client.post(f"/api/projects/{ts}/publish", json={"platform": "x"})
    assert r.status_code == 400


def test_publish_history(app, tmp_path):
    flask_app, ts, ts_path = app
    client = flask_app.test_client()
    Path(ts_path, "metadata.json").write_text(json.dumps({
        "screenplay_name": "x.json",
        "screenplay_path": "screenplay.json",
        "screenplay_sha256": "x" * 64,
        "created_at": "2026-05-06T00:00:00",
        "published_posts": [
            {"platform": "youtube", "video_id": "abc",
             "url": "https://youtube.com/shorts/abc",
             "manual": False, "published_at": "2026-05-06T16:00:00"},
        ],
    }))
    r = client.get(f"/api/projects/{ts}/publish-history")
    assert r.status_code == 200
    posts = r.get_json()["published_posts"]
    assert len(posts) == 1
    assert posts[0]["platform"] == "youtube"
