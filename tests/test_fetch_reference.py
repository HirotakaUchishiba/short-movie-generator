"""Phase 1: scripts/fetch_reference.py の単体テスト。

yt-dlp の subprocess は patch して、ローカルに dummy mp4 を置く形で
fetch + DB 登録の経路を検証する。
"""
from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def fetch_module(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setattr(
        "config.BASE_DIR", str(tmp_path), raising=False,
    )
    # 既に import 済みなので REFERENCE_DIR を tmp_path 配下に上書き
    import scripts.fetch_reference as mod
    importlib.reload(mod)
    monkeypatch.setattr(
        mod, "REFERENCE_DIR", tmp_path / "ref",
    )
    return mod


def _ytdlp_stub_writing(content: bytes):
    """subprocess.run の stub: yt-dlp の代わりに dest path に content を書く。"""
    def _runner(args, **_):
        # args = ["yt-dlp", "-f", "...", "-o", "<path>", ...]
        out_idx = args.index("-o") + 1
        Path(args[out_idx]).write_bytes(content)
        class _Result:
            returncode = 0
        return _Result()
    return _runner


def test_invalid_license_rejected(fetch_module):
    with pytest.raises(ValueError):
        fetch_module.fetch_and_register(
            "https://example.com/x", "unconfirmed",
        )


def test_fetch_inserts_reference_row(fetch_module):
    with patch("subprocess.run", side_effect=_ytdlp_stub_writing(b"FAKE_VIDEO_DATA")):
        out = fetch_module.fetch_and_register(
            "https://example.com/v1", "user_owned",
        )
    assert out["license_status"] == "user_owned"
    assert out["source_url"] == "https://example.com/v1"
    assert Path(out["path"]).exists()
    assert Path(out["path"]).read_bytes() == b"FAKE_VIDEO_DATA"

    # DB 行を確認
    from analytics import db as _db
    with _db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM reference_videos WHERE sha256 = ?",
            (out["sha256"],),
        ).fetchone()
    assert row is not None
    assert row["source_url"] == "https://example.com/v1"
    assert row["license_status"] == "user_owned"
    assert row["fetched_at"]


def test_duplicate_url_updates_last_used(fetch_module):
    with patch("subprocess.run",
               side_effect=_ytdlp_stub_writing(b"SAME_VIDEO")):
        first = fetch_module.fetch_and_register(
            "https://example.com/x", "user_owned",
        )
    with patch("subprocess.run",
               side_effect=_ytdlp_stub_writing(b"SAME_VIDEO")):
        second = fetch_module.fetch_and_register(
            "https://example.com/x", "user_owned",
        )
    assert first["sha256"] == second["sha256"]
    from analytics import db as _db
    with _db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM reference_videos WHERE sha256 = ?",
            (first["sha256"],),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["last_used_at"] is not None


def test_ytdlp_failure_propagates(fetch_module):
    import subprocess
    with patch("subprocess.run",
               side_effect=subprocess.CalledProcessError(1, "yt-dlp")):
        with pytest.raises(RuntimeError, match="yt-dlp failed"):
            fetch_module.fetch_and_register(
                "https://example.com/bad", "user_owned",
            )


def test_ytdlp_missing_binary(fetch_module):
    with patch("subprocess.run", side_effect=FileNotFoundError("yt-dlp")):
        with pytest.raises(RuntimeError, match="yt-dlp failed"):
            fetch_module.fetch_and_register(
                "https://example.com/x", "user_owned",
            )
