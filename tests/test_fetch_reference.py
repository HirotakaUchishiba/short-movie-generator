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


def test_ytdlp_failure_does_not_leak_tmp_file(fetch_module):
    """yt-dlp 失敗時に tempfile.NamedTemporaryFile で作った tmp が残らない
    (= REFERENCE_DIR に未命名の .mp4 が孤立しない)。"""
    import subprocess
    with patch("subprocess.run",
               side_effect=subprocess.CalledProcessError(1, "yt-dlp")):
        with pytest.raises(RuntimeError):
            fetch_module.fetch_and_register(
                "https://example.com/leak", "user_owned",
            )
    ref_dir = fetch_module.REFERENCE_DIR
    leftovers = list(ref_dir.glob("*.mp4")) if ref_dir.exists() else []
    assert leftovers == [], f"tmp file leak: {leftovers}"


def test_sha256_failure_cleans_up_tmp(fetch_module, tmp_path):
    """fetch_with_ytdlp は成功したが _sha256_file が raise した場合に、
    tmp ファイルが必ず unlink される (= disk full 等の保険経路)。"""
    with patch("subprocess.run",
               side_effect=_ytdlp_stub_writing(b"OK_FETCH")):
        with patch.object(fetch_module, "_sha256_file",
                          side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                fetch_module.fetch_and_register(
                    "https://example.com/sha-fail", "user_owned",
                )
    ref_dir = fetch_module.REFERENCE_DIR
    leftovers = list(ref_dir.glob("*.mp4")) if ref_dir.exists() else []
    assert leftovers == [], f"tmp file leak after sha failure: {leftovers}"


def test_ytdlp_uses_merge_output_format_mp4(fetch_module):
    """`--merge-output-format mp4` を yt-dlp に渡し、container を mp4 強制する
    (= best fallback で webm が来ても remux mp4 になる)。"""
    captured: list[list[str]] = []

    def _capturing_runner(args, **_):
        captured.append(list(args))
        # 何か書いておかないと size==0 で reject される
        out_idx = args.index("-o") + 1
        Path(args[out_idx]).write_bytes(b"X")

        class _R:
            returncode = 0
        return _R()

    with patch("subprocess.run", side_effect=_capturing_runner):
        fetch_module.fetch_and_register(
            "https://example.com/m", "user_owned",
        )
    assert captured, "subprocess.run が呼ばれていない"
    args = captured[0]
    assert "--merge-output-format" in args
    assert args[args.index("--merge-output-format") + 1] == "mp4"
