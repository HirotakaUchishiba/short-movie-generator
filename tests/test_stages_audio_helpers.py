"""stages/audio_helpers.py の ffmpeg ラッパ群の smoke / shim 等価性テスト。

scene_gen._extract_audio_segment / _concat_audios_* が薄い shim になった
ため、両系統が同じ実体を呼ぶことを確認する (= リファクタリング後の
regression を防ぐ §3.1.1-d)。
"""
from __future__ import annotations

import os
import subprocess as sp
import wave

import pytest

import scene_gen
from stages import audio_helpers


@pytest.fixture
def silent_aac(tmp_path) -> str:
    """ffmpeg で 1 秒の無音 AAC を作って返す。"""
    out = tmp_path / "silent.m4a"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
        "-t", "1.0",
        "-c:a", "aac", "-b:a", "64k",
        str(out),
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(out)


@pytest.fixture
def silent_mp3(tmp_path) -> str:
    """ffmpeg で 1 秒の無音 mp3 を作って返す。"""
    out = tmp_path / "silent.mp3"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
        "-t", "1.0",
        "-c:a", "libmp3lame", "-q:a", "6",
        str(out),
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(out)


def test_extract_audio_segment_writes_file(tmp_path, silent_mp3):
    out = tmp_path / "out.m4a"
    audio_helpers.extract_audio_segment(
        silent_mp3, 0.2, 0.5, str(out),
    )
    assert out.exists() and out.stat().st_size > 0


def test_convert_to_aac_writes_file(tmp_path, silent_mp3):
    out = tmp_path / "out.m4a"
    audio_helpers.convert_to_aac(silent_mp3, str(out))
    assert out.exists() and out.stat().st_size > 0


def test_concat_audios_to_aac_single_input_just_converts(
    tmp_path, silent_mp3,
):
    out = tmp_path / "out.m4a"
    audio_helpers.concat_audios_to_aac([silent_mp3], str(out))
    assert out.exists() and out.stat().st_size > 0


def test_concat_audios_to_aac_multi_input(tmp_path, silent_mp3):
    out = tmp_path / "out.m4a"
    audio_helpers.concat_audios_to_aac(
        [silent_mp3, silent_mp3], str(out),
    )
    assert out.exists() and out.stat().st_size > 0


def test_concat_audios_to_mp3_single_input_renames(tmp_path, silent_mp3):
    # rename 経路は input を消費するので clone してから渡す
    import shutil
    clone = tmp_path / "clone.mp3"
    shutil.copy(silent_mp3, clone)
    out = tmp_path / "out.mp3"
    audio_helpers.concat_audios_to_mp3([str(clone)], str(out))
    assert out.exists() and out.stat().st_size > 0
    assert not clone.exists()  # os.replace で move されている


def test_concat_audios_to_mp3_multi_input(tmp_path, silent_mp3):
    out = tmp_path / "out.mp3"
    audio_helpers.concat_audios_to_mp3(
        [silent_mp3, silent_mp3], str(out),
    )
    assert out.exists() and out.stat().st_size > 0


def test_concat_audios_empty_input_is_noop(tmp_path):
    out_aac = tmp_path / "noop.m4a"
    audio_helpers.concat_audios_to_aac([], str(out_aac))
    assert not out_aac.exists()
    out_mp3 = tmp_path / "noop.mp3"
    audio_helpers.concat_audios_to_mp3([], str(out_mp3))
    assert not out_mp3.exists()


def test_scene_gen_shims_delegate_to_audio_helpers(monkeypatch):
    """scene_gen.<priv> が stages.audio_helpers.<pub> を呼ぶことを確認する。"""
    calls: list[str] = []

    def fake_extract(*a, **kw):
        calls.append("extract")

    def fake_convert(*a, **kw):
        calls.append("convert")

    def fake_concat_aac(*a, **kw):
        calls.append("concat_aac")

    def fake_concat_mp3(*a, **kw):
        calls.append("concat_mp3")

    def fake_tail():
        calls.append("tail")
        return 0.5

    monkeypatch.setattr(audio_helpers, "extract_audio_segment", fake_extract)
    monkeypatch.setattr(audio_helpers, "convert_to_aac", fake_convert)
    monkeypatch.setattr(audio_helpers, "concat_audios_to_aac", fake_concat_aac)
    monkeypatch.setattr(audio_helpers, "concat_audios_to_mp3", fake_concat_mp3)
    monkeypatch.setattr(audio_helpers, "natural_tail_silence_sec", fake_tail)

    scene_gen._extract_audio_segment("a", 0, 1, "b")
    scene_gen._convert_to_aac("a", "b")
    scene_gen._concat_audios_to_aac(["a"], "b")
    scene_gen._concat_audios_to_mp3(["a"], "b")
    assert scene_gen._natural_tail_silence_sec() == 0.5
    assert calls == ["extract", "convert", "concat_aac", "concat_mp3", "tail"]
