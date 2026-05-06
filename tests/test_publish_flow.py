"""final_import.publish の end-to-end フロー (network mock + analytics DB)。"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


pytestmark = pytest.mark.skipif(
    not _ffmpeg_available(), reason="ffmpeg/ffprobe required",
)


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
def project(tmp_path, monkeypatch):
    import config
    import progress_store

    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(config, "POST_CAPTIONS_DIR", str(tmp_path / "post_captions"))
    Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.POST_CAPTIONS_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))

    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "ref")

    ts = "20260506_140000"
    ts_path = Path(config.TEMP_DIR) / ts
    ts_path.mkdir(parents=True)
    (ts_path / "metadata.json").write_text(json.dumps({
        "screenplay_name": "demo.json",
        "screenplay_path": "screenplay.json",
        "screenplay_sha256": "x" * 64,
        "created_at": "2026-05-06T00:00:00",
    }))
    # screenplay snapshot は publish の caption fallback に必要
    (ts_path / "screenplay.json").write_text(json.dumps({
        "caption": "テストキャプション\n#tag1 #tag2",
        "scenes": [{"lines": [{"text": "a"}]}],
    }))

    for s in ["script", "tts", "bg", "kling", "scene", "overlay"]:
        progress_store.mark_generated(str(ts_path), s)
        progress_store.mark_approved(str(ts_path), s)
    progress_store.mark_generated(str(ts_path), "final")
    progress_store.mark_approved(str(ts_path), "final")

    # post_captions/<title>.md
    cap_md = Path(config.POST_CAPTIONS_DIR) / "demo.md"
    cap_md.write_text("# demo\n\n本文テスト\n#hello #world\n\n## 動画ファイル\n- `/x.mp4`\n")

    # CapCut 出力相当のファイルを Stage 8 取込
    src = tmp_path / "capcut.mp4"
    _make_dummy_mp4(src, duration=2.0)
    from final_import import core as fi
    fi.import_final(ts, src, source="cli", skip_fingerprint=True)
    progress_store.mark_approved(str(ts_path), "final_import")
    return ts, str(ts_path)


class _MockResp:
    def __init__(self, status_code, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def test_publish_youtube_calls_upload_and_registers_post(project, monkeypatch):
    from final_import.publish import publish
    from analytics import db as analytics_db
    import progress_store

    ts, ts_path = project

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": "yt_xyz"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    result = publish(ts, "youtube", privacy="unlisted")
    assert result["platform"] == "youtube"
    assert result["video_id"] == "yt_xyz"
    assert "shorts/yt_xyz" in result["url"]
    assert result["manual"] is False

    # progress_store: publish が generated に
    assert progress_store.is_generated(ts_path, "publish")

    # analytics DB: posts に登録されている
    posts = analytics_db.list_active_posts(platform="youtube")
    assert any(p["platform_post_id"] == "yt_xyz" for p in posts)

    # metadata.json に published_posts が積まれている
    meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    assert any(p["video_id"] == "yt_xyz" for p in meta["published_posts"])


def test_publish_blocked_when_stage8_unapproved(project, monkeypatch):
    import progress_store
    from final_import.publish import publish

    ts, ts_path = project
    # stage 8 を未承認に戻す
    prog = progress_store.load(ts_path)
    prog["stages"]["final_import"]["approved_at"] = None
    progress_store.save(ts_path, prog)

    with pytest.raises(RuntimeError, match="final_import"):
        publish(ts, "youtube")


def test_publish_instagram_semi_auto(project, monkeypatch):
    import sys
    import subprocess as sp
    from final_import.publish import publish

    ts, ts_path = project
    calls: list[list[str]] = []

    real_run = sp.run

    def fake_run(args, **kw):
        calls.append(list(args))

        class R:
            returncode = 0
            stdout = b""
            stderr = b""
        return R()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("subprocess.run", fake_run)

    result = publish(ts, "instagram")
    assert result["manual"] is True
    assert result["platform"] == "instagram"
    # pbcopy + open のいずれかが呼ばれたこと
    assert any(c[0] == "pbcopy" for c in calls)
    assert any(c[0] == "open" for c in calls)
