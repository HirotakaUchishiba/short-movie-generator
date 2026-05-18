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

    def fake_detect(*a, **kw):
        calls.append("detect")
        return []

    def fake_snap(*a, **kw):
        calls.append("snap")
        return []

    def fake_silenceremove(*a, **kw):
        calls.append("silenceremove")

    monkeypatch.setattr(audio_helpers, "extract_audio_segment", fake_extract)
    monkeypatch.setattr(audio_helpers, "convert_to_aac", fake_convert)
    monkeypatch.setattr(audio_helpers, "concat_audios_to_aac", fake_concat_aac)
    monkeypatch.setattr(audio_helpers, "concat_audios_to_mp3", fake_concat_mp3)
    monkeypatch.setattr(audio_helpers, "natural_tail_silence_sec", fake_tail)
    monkeypatch.setattr(audio_helpers, "detect_all_silences", fake_detect)
    monkeypatch.setattr(
        audio_helpers, "snap_line_boundaries_to_silence", fake_snap,
    )
    monkeypatch.setattr(
        audio_helpers, "apply_silenceremove_inplace", fake_silenceremove,
    )

    scene_gen._extract_audio_segment("a", 0, 1, "b")
    scene_gen._convert_to_aac("a", "b")
    scene_gen._concat_audios_to_aac(["a"], "b")
    scene_gen._concat_audios_to_mp3(["a"], "b")
    assert scene_gen._natural_tail_silence_sec() == 0.5
    assert scene_gen._detect_all_silences("a") == []
    assert scene_gen._snap_line_boundaries_to_silence([], []) == []
    scene_gen._apply_silenceremove_inplace("a", 0.5, -35.0)
    assert calls == [
        "extract", "convert", "concat_aac", "concat_mp3", "tail",
        "detect", "snap", "silenceremove",
    ]


def test_snap_line_boundaries_to_silence_preserves_when_no_silence():
    """silence が空なら入力をそのまま (deep copy で) 返す。"""
    line_times = [{"abs_start": 0.5, "abs_end": 1.5}]
    out = audio_helpers.snap_line_boundaries_to_silence(line_times, [])
    assert out == line_times
    assert out is not line_times  # deep copy なので参照は別


def test_snap_line_boundaries_to_silence_snaps_to_nearest():
    """silence.start 近傍に end を snap、silence.end 近傍に start を snap する。"""
    line_times = [{"abs_start": 0.30, "abs_end": 1.45}]
    silences = [(0.0, 0.25), (1.50, 2.0)]
    out = audio_helpers.snap_line_boundaries_to_silence(
        line_times, silences, snap_tolerance_sec=0.2,
    )
    assert out[0]["abs_start"] == pytest.approx(0.25)
    assert out[0]["abs_end"] == pytest.approx(1.50)


def test_split_global_speed_unity_returns_no_correction():
    native, atempo = audio_helpers.split_global_speed(target=1.0)
    assert native == pytest.approx(1.0)
    assert atempo == pytest.approx(1.0)


def test_split_global_speed_above_native_max_uses_atempo(monkeypatch):
    monkeypatch.setattr("config.TTS_NATIVE_SPEED_MIN", 0.7)
    monkeypatch.setattr("config.TTS_NATIVE_SPEED_MAX", 1.2)
    native, atempo = audio_helpers.split_global_speed(target=1.5)
    assert native == pytest.approx(1.2)
    assert atempo == pytest.approx(1.25)


def test_split_global_speed_clamps_extreme():
    # clamp [0.5, 2.0]
    n_low, a_low = audio_helpers.split_global_speed(target=0.1)
    n_hi, a_hi = audio_helpers.split_global_speed(target=10.0)
    # 念のため戻り値が clamp 範囲内
    assert 0.5 <= n_low * a_low <= 2.0
    assert 0.5 <= n_hi * a_hi <= 2.0


def test_full_screenplay_voice_settings_includes_config_defaults(monkeypatch):
    monkeypatch.setattr("config.ELEVENLABS_VOICE_ID", "vid-1")
    monkeypatch.setattr("config.ELEVENLABS_VOICE_STABILITY", 0.42)
    monkeypatch.setattr("config.ELEVENLABS_VOICE_SIMILARITY_BOOST", 0.61)
    monkeypatch.setattr("config.ELEVENLABS_VOICE_STYLE", 0.18)
    monkeypatch.setattr("config.TTS_GLOBAL_SPEED", 1.0)
    vs = audio_helpers.full_screenplay_voice_settings()
    assert vs["voice_id"] == "vid-1"
    assert vs["stability"] == pytest.approx(0.42)
    assert vs["similarity_boost"] == pytest.approx(0.61)
    assert vs["style"] == pytest.approx(0.18)
    assert vs["speed"] == pytest.approx(1.0)


def _build_tone_silence_tone(
    out_path: str, tone_sec: float, silence_sec: float,
) -> None:
    """tone → silence → tone の mp3 を作る (lavfi 3 入力 + concat filter)。"""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={tone_sec}",
        "-f", "lavfi", "-i", f"anullsrc=duration={silence_sec}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={tone_sec}",
        "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
        "-map", "[out]",
        "-c:a", "libmp3lame", "-q:a", "4",
        out_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)


def test_detect_all_silences_finds_inserted_silence(tmp_path):
    """中央に 0.4s の無音を挟んだ mp3 から silence が 1 つ検出される。"""
    out = tmp_path / "with_silence.mp3"
    _build_tone_silence_tone(str(out), tone_sec=0.3, silence_sec=0.4)
    silences = audio_helpers.detect_all_silences(str(out))
    mid_silences = [
        (s, e) for s, e in silences if 0.1 < s < 0.6 and 0.1 < e < 1.0
    ]
    assert len(mid_silences) >= 1


def test_trim_internal_pauses_shrinks_long_silence(tmp_path):
    """tone + 1s 無音 + tone を trim_internal_pauses にかけると尺が縮む。

    config.TTS_PAUSE_KEEP_MS の現行値で実走 (= 既定値 70ms 程度)。
    """
    import json
    src = tmp_path / "src.mp3"
    _build_tone_silence_tone(str(src), tone_sec=0.2, silence_sec=1.0)
    dst = tmp_path / "dst.mp3"
    audio_helpers.trim_internal_pauses(str(src), str(dst))

    def _dur(path: str) -> float:
        r = sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True,
        )
        return float(json.loads(r.stdout)["format"]["duration"])

    assert dst.exists() and dst.stat().st_size > 0
    assert _dur(str(dst)) < _dur(str(src)) - 0.5


def test_apply_silenceremove_inplace_shrinks_silence(tmp_path):
    """tone + 1s 無音 + tone を 100ms 上限で圧縮すると尺が短くなる。"""
    import json
    import shutil
    src = tmp_path / "src.mp3"
    _build_tone_silence_tone(str(src), tone_sec=0.2, silence_sec=1.0)
    target = tmp_path / "target.mp3"
    shutil.copy(src, target)

    def _dur(path: str) -> float:
        r = sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True,
        )
        return float(json.loads(r.stdout)["format"]["duration"])

    before = _dur(str(target))
    audio_helpers.apply_silenceremove_inplace(
        str(target), max_silence_sec=0.1, threshold_db=-30.0,
    )
    after = _dur(str(target))
    assert after < before - 0.5
