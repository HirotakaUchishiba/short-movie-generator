"""映像が TTS 尺に届かない場合の slow_mo 延長 (Kling 5/10s 上限対策) のテスト。"""

import os
import subprocess
from unittest.mock import MagicMock

import pytest

import scene_gen


@pytest.fixture
def temp_dir(tmp_path) -> str:
    return str(tmp_path)


def _make_dummy(path: str, content: bytes = b"x") -> None:
    with open(path, "wb") as f:
        f.write(content)


# ---- _extend_video_to_duration ----------------------------------------------


def test_extend_video_to_duration_skips_when_already_long_enough(
    tmp_path, monkeypatch,
) -> None:
    """target との差が無視できるサイズなら ffmpeg を呼ばずコピーで済ませる。"""
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.mp4"
    _make_dummy(str(src), b"video")

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.05)

    run_spy = MagicMock()
    monkeypatch.setattr(scene_gen.sp, "run", run_spy)

    scene_gen._extend_video_to_duration(str(src), 5.0, str(dst))

    run_spy.assert_not_called()
    assert dst.exists()


def test_extend_video_to_duration_invokes_setpts(tmp_path, monkeypatch) -> None:
    """target > cur のときは setpts=PTS*ratio で ffmpeg を呼ぶ。"""
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.mp4"
    _make_dummy(str(src))

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)

    captured: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        captured.append(cmd)
        # ダミー出力ファイルを作る
        with open(dst, "wb") as f:
            f.write(b"extended")
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        return r

    monkeypatch.setattr(scene_gen.sp, "run", fake_run)

    scene_gen._extend_video_to_duration(str(src), 6.5, str(dst))

    assert len(captured) == 1
    cmd = captured[0]
    assert "ffmpeg" in cmd[0]
    fc_idx = cmd.index("-filter_complex")
    expr = cmd[fc_idx + 1]
    assert "setpts=PTS*" in expr
    # ratio = 6.5 / 5.0 = 1.30
    assert "1.300000" in expr


def test_extend_video_to_duration_warns_when_ratio_too_large(
    tmp_path, monkeypatch, caplog,
) -> None:
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.mp4"
    _make_dummy(str(src))

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 3.0)

    def fake_run(cmd, **_kwargs):
        with open(dst, "wb") as f:
            f.write(b"x")
        r = MagicMock()
        r.returncode = 0
        return r

    monkeypatch.setattr(scene_gen.sp, "run", fake_run)

    import logging
    with caplog.at_level(logging.WARNING, logger="scene_gen"):
        scene_gen._extend_video_to_duration(str(src), 7.0, str(dst))

    assert any("slow_mo ratio" in rec.message for rec in caplog.records)


def test_extend_video_to_duration_raises_on_ffmpeg_failure(
    tmp_path, monkeypatch,
) -> None:
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.mp4"
    _make_dummy(str(src))

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)

    def fake_run(cmd, **_kwargs):
        r = MagicMock()
        r.returncode = 1
        r.stderr = "ffmpeg boom"
        return r

    monkeypatch.setattr(scene_gen.sp, "run", fake_run)

    with pytest.raises(RuntimeError, match="slow_mo extension failed"):
        scene_gen._extend_video_to_duration(str(src), 6.5, str(dst))


# ---- _maybe_extend_video ----------------------------------------------------


def test_maybe_extend_video_skips_when_video_long_enough(
    temp_dir, monkeypatch,
) -> None:
    trim = os.path.join(temp_dir, "scene_000.trim.mp4")
    _make_dummy(trim)

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)
    extend_spy = MagicMock()
    monkeypatch.setattr(scene_gen, "_extend_video_to_duration", extend_spy)

    out = scene_gen._maybe_extend_video(trim, 5.0, 0, temp_dir)

    extend_spy.assert_not_called()
    assert out == trim


def test_maybe_extend_video_extends_when_video_shorter(temp_dir, monkeypatch) -> None:
    trim = os.path.join(temp_dir, "scene_000.trim.mp4")
    _make_dummy(trim)

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)

    def fake_extend(src, target, dst):
        with open(dst, "wb") as f:
            f.write(b"extended")

    monkeypatch.setattr(scene_gen, "_extend_video_to_duration", fake_extend)

    out = scene_gen._maybe_extend_video(trim, 6.5, 0, temp_dir)

    assert out == os.path.join(temp_dir, "scene_000.extended.mp4")
    assert os.path.exists(out)


def test_maybe_extend_video_reuses_cached_extended(temp_dir, monkeypatch) -> None:
    """すでに正しい尺で extended.mp4 がある場合は再生成しない。"""
    trim = os.path.join(temp_dir, "scene_000.trim.mp4")
    extended = os.path.join(temp_dir, "scene_000.extended.mp4")
    _make_dummy(trim)
    _make_dummy(extended, b"old")

    # trim=5.0, extended=6.5 想定
    def fake_dur(p):
        if p.endswith("trim.mp4"):
            return 5.0
        return 6.5

    monkeypatch.setattr(scene_gen, "_get_duration", fake_dur)

    extend_spy = MagicMock()
    monkeypatch.setattr(scene_gen, "_extend_video_to_duration", extend_spy)

    out = scene_gen._maybe_extend_video(trim, 6.5, 0, temp_dir)

    extend_spy.assert_not_called()
    assert out == extended


def test_maybe_extend_video_regenerates_stale_extended(temp_dir, monkeypatch) -> None:
    """target が変わって extended.mp4 が古い場合は再生成する。"""
    trim = os.path.join(temp_dir, "scene_000.trim.mp4")
    extended = os.path.join(temp_dir, "scene_000.extended.mp4")
    _make_dummy(trim)
    _make_dummy(extended, b"stale")

    # trim=5.0, extended=6.0(古い)、target=8.0
    def fake_dur(p):
        if p.endswith("trim.mp4"):
            return 5.0
        return 6.0

    monkeypatch.setattr(scene_gen, "_get_duration", fake_dur)

    def fake_extend(src, target, dst):
        with open(dst, "wb") as f:
            f.write(b"new")

    extend_spy = MagicMock(side_effect=fake_extend)
    monkeypatch.setattr(scene_gen, "_extend_video_to_duration", extend_spy)

    out = scene_gen._maybe_extend_video(trim, 8.0, 0, temp_dir)

    extend_spy.assert_called_once()
    assert out == extended


# ---- _scene_video_for_scene 統合 -------------------------------------------


def _base_scene(duration: float = 5.0) -> dict:
    return {
        "duration": duration,
        "background_prompt": "bg",
        "animation_prompt": "motion",
        "lines": [{"text": "セリフ", "start": 0.0, "end": 3.0}],
    }


def test_scene_video_passes_extended_path_to_lipsync(temp_dir, monkeypatch) -> None:
    """TTS 尺 > 動画尺 の場合、lipsync には extended 動画が渡される。"""
    monkeypatch.setattr(scene_gen.config, "LIPSYNC_ENABLED", True)
    monkeypatch.setattr(scene_gen, "_validate_lipsynced_scene",
                          lambda *a, **kw: True)
    trim = os.path.join(temp_dir, "scene_000.trim.mp4")
    audio = os.path.join(temp_dir, "audio_000.m4a")
    _make_dummy(trim)
    _make_dummy(audio)

    # trim=5.0, audio=6.5, scene.duration=6.5
    def fake_dur(p):
        if p.endswith("trim.mp4"):
            return 5.0
        if p.endswith("audio_000.m4a"):
            return 6.5
        if p.endswith("extended.mp4"):
            return 6.5
        return 5.0

    monkeypatch.setattr(scene_gen, "_get_duration", fake_dur)

    def fake_extend(src, target, dst):
        with open(dst, "wb") as f:
            f.write(b"extended")

    monkeypatch.setattr(scene_gen, "_extend_video_to_duration", fake_extend)

    captured = {}

    def fake_apply(v, a, out):
        captured["video_in"] = v
        with open(out, "wb") as f:
            f.write(b"lipsynced")

    monkeypatch.setattr(scene_gen.lipsync_client, "apply",
                        MagicMock(side_effect=fake_apply))

    scene_gen._scene_video_for_scene(
        0, _base_scene(duration=6.5), {}, temp_dir,
    )

    assert captured["video_in"] == os.path.join(temp_dir, "scene_000.extended.mp4")


def test_scene_video_uses_trim_directly_when_long_enough(
    temp_dir, monkeypatch,
) -> None:
    """動画尺が音声以上なら extended は作らない。"""
    monkeypatch.setattr(scene_gen.config, "LIPSYNC_ENABLED", True)
    monkeypatch.setattr(scene_gen, "_validate_lipsynced_scene",
                          lambda *a, **kw: True)
    trim = os.path.join(temp_dir, "scene_000.trim.mp4")
    audio = os.path.join(temp_dir, "audio_000.m4a")
    _make_dummy(trim)
    _make_dummy(audio)

    def fake_dur(p):
        if p.endswith("trim.mp4"):
            return 5.0
        if p.endswith("audio_000.m4a"):
            return 4.0
        return 5.0

    monkeypatch.setattr(scene_gen, "_get_duration", fake_dur)

    extend_spy = MagicMock()
    monkeypatch.setattr(scene_gen, "_extend_video_to_duration", extend_spy)

    captured = {}

    def fake_apply(v, a, out):
        captured["video_in"] = v
        with open(out, "wb") as f:
            f.write(b"lipsynced")

    monkeypatch.setattr(scene_gen.lipsync_client, "apply",
                        MagicMock(side_effect=fake_apply))

    scene_gen._scene_video_for_scene(
        0, _base_scene(duration=5.0), {}, temp_dir,
    )

    extend_spy.assert_not_called()
    assert captured["video_in"] == trim


