import importlib
import logging
import os
from logging.handlers import RotatingFileHandler

import pytest


@pytest.fixture
def reload_log_setup(monkeypatch, tmp_path):
    """log_setup と config を毎回リロードして初期化フラグをクリアする。"""
    import config as _config

    log_path = tmp_path / "server.log"
    monkeypatch.setenv("LOG_FILE", str(log_path))
    monkeypatch.setenv("LOG_MAX_BYTES", "1024")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "3")
    importlib.reload(_config)

    import log_setup as _log_setup
    importlib.reload(_log_setup)
    yield _log_setup, log_path
    # cleanup root logger handlers to avoid leaking RotatingFileHandlers
    root = logging.getLogger()
    for h in list(root.handlers):
        try:
            h.close()
        except Exception:
            pass
        root.removeHandler(h)


def test_setup_uses_rotating_file_handler(reload_log_setup) -> None:
    log_setup, log_path = reload_log_setup
    log_setup.setup()
    root = logging.getLogger()
    rotating = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(rotating) == 1
    h = rotating[0]
    assert h.maxBytes == 1024
    assert h.backupCount == 3


def test_request_id_appears_in_log_output(reload_log_setup) -> None:
    log_setup, log_path = reload_log_setup
    log_setup.setup()
    log_setup.set_request_id("rid-test-1234")
    logger = logging.getLogger("test_correlation")
    logger.warning("hello-correlated")
    # flush handlers
    for h in logging.getLogger().handlers:
        h.flush()
    body = log_path.read_text(encoding="utf-8")
    assert "rid-test-1234" in body
    assert "hello-correlated" in body


def test_set_request_id_generates_id_when_none(reload_log_setup) -> None:
    log_setup, _ = reload_log_setup
    log_setup.reset_request_id()
    rid = log_setup.set_request_id(None)
    assert rid != "-"
    assert len(rid) >= 8
    assert log_setup.get_request_id() == rid


def test_log_rotates_when_max_bytes_exceeded(reload_log_setup) -> None:
    log_setup, log_path = reload_log_setup
    log_setup.setup()
    logger = logging.getLogger("test_rotation")
    # write > 1024 bytes to trigger rotation
    for i in range(200):
        logger.warning("x" * 100 + " line=%d", i)
    for h in logging.getLogger().handlers:
        h.flush()
    backup_path = log_path.with_suffix(".log.1")
    assert backup_path.exists() or os.path.exists(str(log_path) + ".1")
