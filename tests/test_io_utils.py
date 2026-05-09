import json
import os
from unittest.mock import patch

import pytest

import io_utils


def test_atomic_write_bytes_creates_file(tmp_path):
    p = str(tmp_path / "out.bin")
    io_utils.atomic_write_bytes(p, b"hello")
    assert os.path.exists(p)
    with open(p, "rb") as f:
        assert f.read() == b"hello"


def test_atomic_write_bytes_overwrites(tmp_path):
    p = str(tmp_path / "out.bin")
    io_utils.atomic_write_bytes(p, b"first")
    io_utils.atomic_write_bytes(p, b"second")
    with open(p, "rb") as f:
        assert f.read() == b"second"


def test_atomic_write_bytes_no_tmp_left_on_success(tmp_path):
    p = str(tmp_path / "out.bin")
    io_utils.atomic_write_bytes(p, b"x")
    assert not os.path.exists(p + ".tmp")


def test_atomic_write_bytes_keeps_old_on_failure(tmp_path):
    """書き込み中に例外が起きても元ファイルは無傷で残る。"""
    p = str(tmp_path / "out.bin")
    io_utils.atomic_write_bytes(p, b"original")

    real_replace = os.replace

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    with patch("os.replace", side_effect=boom):
        with pytest.raises(OSError):
            io_utils.atomic_write_bytes(p, b"corrupted")

    with open(p, "rb") as f:
        assert f.read() == b"original"
    assert not os.path.exists(p + ".tmp")
    assert real_replace is os.replace


def test_atomic_write_text_utf8(tmp_path):
    p = str(tmp_path / "out.txt")
    io_utils.atomic_write_text(p, "日本語テキスト")
    with open(p, encoding="utf-8") as f:
        assert f.read() == "日本語テキスト"


def test_atomic_write_json(tmp_path):
    p = str(tmp_path / "out.json")
    io_utils.atomic_write_json(p, {"k": "値", "n": 1})
    with open(p) as f:
        data = json.load(f)
    assert data == {"k": "値", "n": 1}


def test_atomic_write_bytes_does_not_leak_tmp_on_write_failure(tmp_path):
    """write 中に例外が起きても .tmp は片付けられる。"""
    p = str(tmp_path / "out.bin")

    class BadBytes(bytes):
        pass

    real_open = open

    def fake_open(path, *a, **kw):
        f = real_open(path, *a, **kw)
        if path == p + ".tmp":
            orig_write = f.write

            def bad_write(_data):
                orig_write(b"partial")
                raise IOError("simulated mid-write failure")

            f.write = bad_write  # type: ignore[method-assign]
        return f

    with patch("io_utils.open", side_effect=fake_open):
        with pytest.raises(IOError):
            io_utils.atomic_write_bytes(p, b"complete")

    assert not os.path.exists(p)
    assert not os.path.exists(p + ".tmp")


# ─── retry helpers ────────────────────────────────────────────


def test_parse_retry_after_seconds():
    assert io_utils.parse_retry_after("30") == 30.0
    assert io_utils.parse_retry_after("  10.5  ") == 10.5
    assert io_utils.parse_retry_after("0") == 0.0


def test_parse_retry_after_invalid():
    assert io_utils.parse_retry_after(None) is None
    assert io_utils.parse_retry_after("") is None
    assert io_utils.parse_retry_after("Wed, 21 Oct 2015") is None
    assert io_utils.parse_retry_after("xx") is None


def test_parse_retry_after_negative_clamps_to_zero():
    assert io_utils.parse_retry_after("-5") == 0.0


def test_next_backoff_uses_schedule_index():
    schedule = [10.0, 20.0, 40.0]
    assert io_utils.next_backoff_seconds(0, schedule, jitter=0) == 10.0
    assert io_utils.next_backoff_seconds(1, schedule, jitter=0) == 20.0
    assert io_utils.next_backoff_seconds(2, schedule, jitter=0) == 40.0
    # 範囲外は最後の値で saturate
    assert io_utils.next_backoff_seconds(10, schedule, jitter=0) == 40.0


def test_next_backoff_jitter_within_range():
    base = 100.0
    schedule = [base]
    for _ in range(50):
        v = io_utils.next_backoff_seconds(0, schedule, jitter=0.3)
        assert 70.0 <= v <= 130.0


def test_next_backoff_retry_after_overrides_schedule():
    """Retry-After 値があればスケジュールを無視。"""
    schedule = [10.0, 20.0, 40.0]
    v = io_utils.next_backoff_seconds(
        2, schedule, jitter=0, retry_after=5.0,
    )
    assert v == 5.0


def test_next_backoff_no_negative():
    """大きな jitter でもマイナス秒にはならない。"""
    schedule = [1.0]
    for _ in range(20):
        v = io_utils.next_backoff_seconds(0, schedule, jitter=2.0)
        assert v >= 0.0
