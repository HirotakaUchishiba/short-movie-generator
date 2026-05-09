"""`temp/<TS>/final/*.mp4` を監視し、新規ファイルを Stage 8 に取り込む。

CapCut が逐次書き出すあいだは on_modified が連発するので、
- パスごとに最終 size/event 時刻を記憶
- size が `STABLE_WINDOW_SEC` 秒変動しなくなったら "stable" 候補
- 候補に対して **排他オープン** と **ffprobe での moov atom 検証** を追加
  (= ネットワーク drag stall や mid-copy の不完全 mp4 を排除する)
- 全部通ったら import_final を呼ぶ

preview_server 起動時に start_watcher() を呼んで Observer をバックグラウンド
スレッドで動かす。停止は stop_watcher()。

STABLE_WINDOW_SEC は環境変数 ``FINAL_WATCHER_STABLE_SEC`` で override 可能
(= 遅いネットワーク drag では 10〜15 秒推奨)。
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import config

from .core import ALLOWED_EXTS, FINAL_DIR_NAME, import_final, list_final_versions

logger = logging.getLogger(__name__)


def _stable_window_sec() -> float:
    raw = os.environ.get("FINAL_WATCHER_STABLE_SEC")
    if raw:
        try:
            v = float(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return 3.0


STABLE_WINDOW_SEC = _stable_window_sec()
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


SLOW_WRITE_WARN_SEC = 5.0


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
        now = time.time()
        rec.update({
            "ts": ts, "path": resolved,
            "size": size, "last_seen": now,
        })
        rec.setdefault("first_seen", now)
        rec.setdefault("warned_slow", False)
        _pending[str(resolved)] = rec


def _can_open_exclusive(path: Path) -> bool:
    """ファイルを読み取り専用で開いて末尾 1 byte を読めるか確認。

    mid-copy / open file handle で moov atom が未確定の状態を排除する。
    macOS の fcntl では強い排他保証は無いが、サイズ取得 + 末尾 read が
    EBUSY や IOError を返す状況で取込を防ぐには十分。
    """
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            tail = f.tell()
            if tail <= 0:
                return False
            f.seek(max(0, tail - 1))
            f.read(1)
        return True
    except OSError as e:
        logger.debug("[watcher] 排他チェック失敗 %s: %s", path, e)
        return False


def _has_valid_moov(path: Path) -> bool:
    """ffprobe で format.duration が取れるか (= moov atom が完成しているか)。

    mp4 の途中まで書かれただけのファイルは ffprobe が duration を返せない。
    ffprobe が PATH に無い環境ではこのチェックを skip する (= 真を返す)。
    """
    if shutil.which("ffprobe") is None:
        return True
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug("[watcher] ffprobe 例外 %s: %s", path, e)
        return False
    if r.returncode != 0:
        return False
    try:
        data = json.loads(r.stdout or "{}")
        dur = float((data.get("format") or {}).get("duration") or 0.0)
    except (json.JSONDecodeError, ValueError):
        return False
    return dur > 0.0


def _is_ready_for_import(path: Path) -> bool:
    """size 安定の後に追加で行う最終検証 (排他オープン + moov 完全性)。"""
    if not _can_open_exclusive(path):
        return False
    if not _has_valid_moov(path):
        return False
    return True


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
                    if not _is_ready_for_import(rec["path"]):
                        # まだ書込中 / moov 未確定 — last_seen を更新して再待機。
                        # ただし first_seen から SLOW_WRITE_WARN_SEC 経って取り込めない
                        # 場合は 1 度だけ WARN ログを出す (= ネットワーク drag stall や
                        # 巨大ファイルのコピーが詰まっているサイン)。
                        first_seen = rec.get("first_seen", now)
                        if (not rec.get("warned_slow")
                                and now - first_seen >= SLOW_WRITE_WARN_SEC):
                            logger.warning(
                                "[取込] %s が %ds 経過しても import 可になりません "
                                "(slow write / moov 未確定の可能性)",
                                rec["path"].name, int(now - first_seen),
                            )
                            rec["warned_slow"] = True
                        rec["last_seen"] = now
                        continue
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
    logger.info("[取込] watchdog start: %s", base)
    return True


def stop_watcher() -> None:
    global _observer, _poller_thread
    with _observer_lock:
        if _observer is not None:
            try:
                _observer.stop()
                _observer.join(timeout=2)
            except Exception as e:
                logger.warning("[取込] watchdog 停止時に例外: %s", e)
            _observer = None
    _poller_stop.set()
    if _poller_thread is not None:
        _poller_thread.join(timeout=2)
        _poller_thread = None
    with _pending_lock:
        _pending.clear()
