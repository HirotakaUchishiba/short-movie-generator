"""`temp/<TS>/final/*.mp4` を監視し、新規ファイルを Stage 8 に取り込む。

CapCut が逐次書き出すあいだは on_modified が連発するので、
- パスごとに最終 size/event 時刻を記憶
- size が `STABLE_WINDOW_SEC` 秒変動しなくなったら "stable" 判定
- import_final を呼ぶ

preview_server 起動時に start_watcher() を呼んで Observer をバックグラウンド
スレッドで動かす。停止は stop_watcher()。
"""

import logging
import os
import re
import threading
import time
from pathlib import Path

import config

from .core import ALLOWED_EXTS, FINAL_DIR_NAME, import_final, list_final_versions

logger = logging.getLogger(__name__)

STABLE_WINDOW_SEC = 3.0
POLL_INTERVAL_SEC = 1.0
TS_PATTERN = re.compile(r"^\d{8}_\d{6}$")


_observer_lock = threading.Lock()
_observer = None  # type: ignore[var-annotated]
_pending: dict[str, dict] = {}
_pending_lock = threading.Lock()
_poller_thread: threading.Thread | None = None
_poller_stop = threading.Event()


def _is_final_file(path: Path) -> tuple[str, Path] | None:
    """path が `temp/<TS>/final/<name>` か判定。該当なら (ts, path)、そうでなければ None。"""
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if resolved.suffix.lower() not in ALLOWED_EXTS:
        return None
    parts = resolved.parts
    if len(parts) < 3:
        return None
    if parts[-2] != FINAL_DIR_NAME:
        return None
    ts = parts[-3]
    if not TS_PATTERN.match(ts):
        return None
    return ts, resolved


def _is_already_imported(ts: str, path: Path) -> bool:
    ts_path = os.path.join(config.TEMP_DIR, ts)
    try:
        size = path.stat().st_size
    except OSError:
        return False
    for v in list_final_versions(ts_path):
        if v.filename == path.name and v.size_bytes == size:
            return True
    return False


def handle_event(path: Path) -> None:
    """イベント発生時に呼ぶ。pending 表に登録 (or 既存エントリを更新) する。"""
    res = _is_final_file(path)
    if res is None:
        return
    ts, resolved = res
    if _is_already_imported(ts, resolved):
        return
    try:
        size = resolved.stat().st_size
    except OSError:
        return
    if size <= 0:
        return
    with _pending_lock:
        rec = _pending.get(str(resolved)) or {}
        rec.update({
            "ts": ts, "path": resolved,
            "size": size, "last_seen": time.time(),
        })
        _pending[str(resolved)] = rec


def _poll_pending() -> None:
    while not _poller_stop.is_set():
        time.sleep(POLL_INTERVAL_SEC)
        now = time.time()
        ready: list[dict] = []
        with _pending_lock:
            for key, rec in list(_pending.items()):
                try:
                    cur = rec["path"].stat().st_size
                except OSError:
                    _pending.pop(key, None)
                    continue
                if cur != rec["size"]:
                    rec["size"] = cur
                    rec["last_seen"] = now
                    continue
                if now - rec["last_seen"] >= STABLE_WINDOW_SEC:
                    ready.append(rec)
                    _pending.pop(key, None)
        for rec in ready:
            try:
                import_final(rec["ts"], rec["path"], source="watch")
            except Exception as e:
                logger.warning(
                    "watcher 取込失敗 %s: %s", rec["path"], e,
                )


def start_watcher(temp_dir: str | None = None) -> bool:
    """temp_dir 配下の `*/final/` を監視開始。watchdog 未インストールなら False。"""
    global _observer, _poller_thread
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        logger.warning("watchdog が未インストール — watcher を起動しません")
        return False

    base = Path(temp_dir or config.TEMP_DIR)
    base.mkdir(parents=True, exist_ok=True)

    class Handler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.is_directory:
                return
            handle_event(Path(event.src_path))

        def on_created(self, event):
            if event.is_directory:
                return
            handle_event(Path(event.src_path))

        def on_moved(self, event):
            if event.is_directory:
                return
            handle_event(Path(event.dest_path))

    with _observer_lock:
        if _observer is not None:
            return True
        obs = Observer()
        obs.schedule(Handler(), str(base), recursive=True)
        obs.start()
        _observer = obs
        _poller_stop.clear()
        _poller_thread = threading.Thread(
            target=_poll_pending, name="final-watch-poll", daemon=True,
        )
        _poller_thread.start()
    logger.info("[Stage 8] watchdog start: %s", base)
    return True


def stop_watcher() -> None:
    global _observer, _poller_thread
    with _observer_lock:
        if _observer is not None:
            try:
                _observer.stop()
                _observer.join(timeout=2)
            except Exception:
                pass
            _observer = None
    _poller_stop.set()
    if _poller_thread is not None:
        _poller_thread.join(timeout=2)
        _poller_thread = None
    with _pending_lock:
        _pending.clear()
