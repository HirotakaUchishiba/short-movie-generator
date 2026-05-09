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


def test_is_ready_for_import_rejects_truncated_mp4(tmp_path):
    """size 安定でも moov atom 不在のファイルは取込候補から除外される。"""
    from final_import import watcher as w
    truncated = tmp_path / "broken.mp4"
    truncated.write_bytes(b"\x00" * 1024)  # ffprobe 不可な dummy
    assert w._is_ready_for_import(truncated) is False


def test_is_ready_for_import_accepts_valid_mp4(tmp_path):
    """有効な mp4 は排他オープン + moov 検証を通過する。"""
    from final_import import watcher as w
    good = tmp_path / "good.mp4"
    _make_dummy_mp4(good, duration=0.5)
    assert w._is_ready_for_import(good) is True


def test_can_open_exclusive_rejects_zero_byte(tmp_path):
    from final_import import watcher as w
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert w._can_open_exclusive(empty) is False


def test_poll_skips_import_when_moov_not_ready(project, tmp_path, monkeypatch):
    """size 安定でも moov 検証で reject されると import_final が呼ばれない。"""
    from final_import import watcher as w
    import progress_store

    ts, ts_path = project
    final_dir = Path(ts_path) / "final"
    truncated = final_dir / "incomplete.mp4"
    truncated.write_bytes(b"\x00" * 4096)  # 1 byte 以上だが mp4 として無効

    monkeypatch.setattr(w, "STABLE_WINDOW_SEC", 0.05)

    called = {"n": 0}

    def fake_import(ts, path, source="watch"):
        called["n"] += 1

    monkeypatch.setattr(w, "import_final", fake_import)

    w.handle_event(truncated)
    w._poller_stop.clear()
    poll_thread = __import__("threading").Thread(target=w._poll_pending, daemon=True)
    poll_thread.start()
    time.sleep(0.5)
    w._poller_stop.set()
    poll_thread.join(timeout=1)

    assert called["n"] == 0, "壊れた mp4 が誤って取り込まれている"
    # progress_store も触られていない
    assert not progress_store.is_generated(ts_path, "final_import")


def test_stable_window_env_override(monkeypatch):
    """FINAL_WATCHER_STABLE_SEC 環境変数で window を変更できる。"""
    monkeypatch.setenv("FINAL_WATCHER_STABLE_SEC", "12.5")
    # _stable_window_sec は import 時に評価されるので、再 import で確認
    import importlib
    from final_import import watcher as w
    importlib.reload(w)
    assert w.STABLE_WINDOW_SEC == 12.5
    monkeypatch.delenv("FINAL_WATCHER_STABLE_SEC", raising=False)
    importlib.reload(w)
    assert w.STABLE_WINDOW_SEC == 3.0


def test_slow_write_emits_warning_once(project, tmp_path, monkeypatch, caplog):
    """import 不可な状態が SLOW_WRITE_WARN_SEC 以上続くと WARN を 1 回出す。"""
    import logging as _logging
    from final_import import watcher as w

    ts, ts_path = project
    final_dir = Path(ts_path) / "final"
    src = final_dir / "broken.mp4"
    src.write_bytes(b"\x00" * 1024)  # ffprobe 不可なダミー → _is_ready_for_import False

    monkeypatch.setattr(w, "STABLE_WINDOW_SEC", 0.0)
    monkeypatch.setattr(w, "SLOW_WRITE_WARN_SEC", 0.05)

    w.handle_event(src)
    # first_seen を 1 秒前にずらす (= SLOW_WRITE_WARN_SEC を確実に超えさせる)
    with w._pending_lock:
        for rec in w._pending.values():
            rec["first_seen"] -= 1.0

    caplog.set_level(_logging.WARNING, logger="final_import.watcher")
    w._poller_stop.clear()
    poll_thread = __import__("threading").Thread(target=w._poll_pending, daemon=True)
    poll_thread.start()
    time.sleep(1.5 * w.POLL_INTERVAL_SEC + 0.3)
    w._poller_stop.set()
    poll_thread.join(timeout=1)

    matching = [
        r for r in caplog.records
        if "import 可になりません" in r.getMessage()
    ]
    assert len(matching) == 1  # 同じ rec から 2 回 WARN は出ない
