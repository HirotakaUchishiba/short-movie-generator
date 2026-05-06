"""watchdog ベースの Stage 8 自動取込テスト。"""

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytest.importorskip("watchdog")


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
def project(tmp_path, monkeypatch):
    import config
    import progress_store

    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    ts = "20260506_150000"
    ts_path = Path(config.TEMP_DIR) / ts
    ts_path.mkdir(parents=True)
    (ts_path / "metadata.json").write_text(json.dumps({
        "screenplay_name": "x.json", "screenplay_path": "screenplay.json",
        "screenplay_sha256": "x" * 64, "created_at": "2026-05-06T00:00:00",
    }))
    for s in ["script", "tts", "bg", "kling", "scene", "overlay"]:
        progress_store.mark_generated(str(ts_path), s)
        progress_store.mark_approved(str(ts_path), s)
    (ts_path / "final").mkdir()
    return ts, str(ts_path)


def test_handle_event_imports_stable_file(project, tmp_path, monkeypatch):
    """handle_event 経由で size 安定後に import_final が走ることを確認。

    実 watchdog Observer は使わず、handle_event + _poll_pending を直接駆動する
    (= タイミングに依存しないユニットテスト)。
    """
    import config
    from final_import import watcher as w
    import progress_store

    ts, ts_path = project
    final_dir = Path(ts_path) / "final"
    src = tmp_path / "capcut.mp4"
    _make_dummy_mp4(src, duration=1.0)
    dst = final_dir / "out.mp4"
    shutil.copyfile(src, dst)

    # STABLE_WINDOW を短く
    monkeypatch.setattr(w, "STABLE_WINDOW_SEC", 0.05)

    captured = {}

    def fake_import(ts, path, source="watch"):
        captured["ts"] = ts
        captured["path"] = Path(path)
        captured["source"] = source
        progress_store.mark_generated(
            str(Path(config.TEMP_DIR) / ts), "final_import",
        )

    monkeypatch.setattr(w, "import_final", fake_import)

    w.handle_event(dst)
    time.sleep(0.2)
    # poll を 1 周だけ手動実行
    w._poller_stop.clear()
    poll_thread = __import__("threading").Thread(target=w._poll_pending, daemon=True)
    poll_thread.start()
    time.sleep(0.5)
    w._poller_stop.set()
    poll_thread.join(timeout=1)

    assert captured.get("ts") == ts
    assert captured["path"].name == "out.mp4"
    assert captured["source"] == "watch"


def test_handle_event_ignores_unrelated_paths(tmp_path, monkeypatch):
    from final_import import watcher as w

    called = {"n": 0}

    def fake_import(*args, **kwargs):
        called["n"] += 1

    monkeypatch.setattr(w, "import_final", fake_import)
    monkeypatch.setattr(w, "STABLE_WINDOW_SEC", 0.05)

    # final/ に入らないパス
    other = tmp_path / "random" / "x.mp4"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"x")
    w.handle_event(other)

    # 拡張子が違う
    bad = tmp_path / "temp" / "20260101_000000" / "final" / "x.txt"
    bad.parent.mkdir(parents=True)
    bad.write_text("nope")
    w.handle_event(bad)

    # TS パターン外
    bad2 = tmp_path / "temp" / "notaTS" / "final" / "v.mp4"
    bad2.parent.mkdir(parents=True)
    bad2.write_bytes(b"x")
    w.handle_event(bad2)

    time.sleep(0.2)
    assert called["n"] == 0


def test_start_stop_watcher_does_not_raise(tmp_path, monkeypatch):
    import config
    from final_import import watcher as w
    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path / "temp"))
    Path(config.TEMP_DIR).mkdir()
    assert w.start_watcher() is True
    w.stop_watcher()
