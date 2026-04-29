"""analyze.cache の単体テスト (content-addressed cache)。"""
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """テストごとに分離した CACHE_ROOT を使う。"""
    from analyze import cache as _cache
    monkeypatch.setattr(_cache, "CACHE_ROOT", tmp_path / "cache")
    return _cache


def test_file_sha256_consistent(tmp_path, isolated_cache) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello world")
    h1 = isolated_cache.file_sha256(p)
    h2 = isolated_cache.file_sha256(str(p))
    assert h1 == h2
    assert len(h1) == 64


def test_segments_signature_stable(isolated_cache) -> None:
    t1 = {"segments": [{"start": 0.0, "end": 1.0, "text": "a"},
                        {"start": 1.0, "end": 2.0, "text": "b"}]}
    t2 = {"segments": [{"end": 1.0, "start": 0.0, "text": "a"},
                        {"end": 2.0, "start": 1.0, "text": "b"}]}
    # キー順が違っても sort_keys で同じ hash
    assert isolated_cache.segments_signature(t1) == isolated_cache.segments_signature(t2)
    # 違う segments なら違う hash
    t3 = {"segments": [{"start": 0.0, "end": 1.0, "text": "z"}]}
    assert isolated_cache.segments_signature(t1) != isolated_cache.segments_signature(t3)


def test_get_json_miss_returns_none(isolated_cache) -> None:
    assert isolated_cache.get_json("transcript", "no_such_key") is None


def test_put_then_get_json(isolated_cache) -> None:
    payload = {"text": "あいう", "segments": [{"text": "a", "start": 0, "end": 1}]}
    isolated_cache.put_json("transcript", "abc123", payload)
    got = isolated_cache.get_json("transcript", "abc123")
    assert got == payload


def test_put_json_atomic_replace(isolated_cache, tmp_path) -> None:
    """tmp ファイル経由で原子的に置換する (途中で読まれても破損しない)。"""
    isolated_cache.put_json("bgm", "k", {"present": True})
    isolated_cache.put_json("bgm", "k", {"present": False})
    assert isolated_cache.get_json("bgm", "k") == {"present": False}


def test_unknown_kind_raises(isolated_cache) -> None:
    with pytest.raises(ValueError):
        isolated_cache.get_json("unknown_kind", "x")


def test_acoustic_key_changes_with_segments(isolated_cache) -> None:
    audio_sha = "a" * 64
    t1 = {"segments": [{"start": 0, "end": 1, "text": "x"}]}
    t2 = {"segments": [{"start": 0, "end": 1, "text": "y"}]}
    k1 = isolated_cache.acoustic_key(audio_sha, t1)
    k2 = isolated_cache.acoustic_key(audio_sha, t2)
    assert k1 != k2
    assert audio_sha[:16] in k1


# ─── frames cache ───────────────────────────────────────────────


def test_frames_round_trip(isolated_cache, tmp_path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8frame1")
    (src_dir / "frame_0002.jpg").write_bytes(b"\xff\xd8frame2")
    (src_dir / "ignored.txt").write_text("noise")  # 非対象

    video_sha = "v" * 64
    isolated_cache.store_frames(video_sha, 2.0, str(src_dir))
    assert isolated_cache.has_frames(video_sha, 2.0)

    dest_dir = tmp_path / "restored"
    paths = isolated_cache.restore_frames(video_sha, 2.0, str(dest_dir))
    assert paths is not None
    assert len(paths) == 2
    assert all(p.endswith(".jpg") for p in paths)
    # ignored.txt は復元されない
    assert not (dest_dir / "ignored.txt").exists()


def test_restore_frames_miss_returns_none(isolated_cache, tmp_path) -> None:
    assert isolated_cache.restore_frames("nope" * 16, 2.0, str(tmp_path / "x")) is None


def test_frames_key_includes_fps(isolated_cache, tmp_path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "frame_0001.jpg").write_bytes(b"x")
    sha = "z" * 64
    isolated_cache.store_frames(sha, 2.0, str(src))
    assert isolated_cache.has_frames(sha, 2.0)
    assert not isolated_cache.has_frames(sha, 4.0)


# ─── 管理ユーティリティ ─────────────────────────────────────────


def test_clear_specific_kind(isolated_cache) -> None:
    isolated_cache.put_json("transcript", "k1", {"a": 1})
    isolated_cache.put_json("bgm", "k2", {"b": 2})
    n = isolated_cache.clear("transcript")
    assert n == 1
    assert isolated_cache.get_json("transcript", "k1") is None
    assert isolated_cache.get_json("bgm", "k2") == {"b": 2}


def test_clear_all(isolated_cache) -> None:
    isolated_cache.put_json("transcript", "k1", {"a": 1})
    isolated_cache.put_json("bgm", "k2", {"b": 2})
    n = isolated_cache.clear()
    assert n == 2
    assert isolated_cache.get_json("transcript", "k1") is None
    assert isolated_cache.get_json("bgm", "k2") is None


def test_stats_counts(isolated_cache) -> None:
    isolated_cache.put_json("transcript", "a", {})
    isolated_cache.put_json("transcript", "b", {})
    isolated_cache.put_json("bgm", "c", {})
    s = isolated_cache.stats()
    assert s["transcript"] == 2
    assert s["bgm"] == 1
    assert s["acoustic"] == 0
