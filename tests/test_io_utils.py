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
