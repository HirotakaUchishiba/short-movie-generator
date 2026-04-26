import os
import subprocess

import pytest


@pytest.fixture
def synth_wav(tmp_path) -> str:
    """ffmpeg lavfiで2秒の440Hz正弦波WAVを生成。"""
    path = str(tmp_path / "sine.wav")
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=2",
        "-ac", "1", "-ar", "16000",
        path,
    ], capture_output=True, check=True)
    return path


def test_extract_phrase_features_returns_expected_keys(synth_wav) -> None:
    pytest.importorskip("librosa")
    import audio_features

    feat = audio_features.extract_phrase_features(synth_wav, 0.0, 1.0)
    for key in ("pitch_hz_mean", "pitch_hz_max", "pitch_trend", "rms_peak", "rms_mean", "duration"):
        assert key in feat
    assert feat["duration"] == pytest.approx(1.0, rel=0.1)


def test_extract_phrase_features_detects_pitch_on_sine(synth_wav) -> None:
    pytest.importorskip("librosa")
    import audio_features

    feat = audio_features.extract_phrase_features(synth_wav, 0.0, 1.0)
    assert 420 <= feat["pitch_hz_mean"] <= 460


def test_extract_phrase_features_short_region(synth_wav) -> None:
    pytest.importorskip("librosa")
    import audio_features

    feat = audio_features.extract_phrase_features(synth_wav, 0.0, 0.01)
    assert feat["pitch_hz_mean"] == 0.0
    assert feat["pitch_trend"] == "flat"


def test_wpm_from_text_zero_duration() -> None:
    import audio_features
    assert audio_features.wpm_from_text("text", 0) == 0.0


def test_wpm_from_text_normal() -> None:
    import audio_features
    assert audio_features.wpm_from_text("あいうえお", 1.0) == 300.0


@pytest.fixture
def speech_then_silence_wav(tmp_path) -> str:
    """先頭1秒に音、その後2秒の無音を持つWAVを生成。"""
    path = str(tmp_path / "mixed.wav")
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=1",
        "-f", "lavfi",
        "-i", "anullsrc=r=16000:cl=mono:d=2",
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[out]",
        "-map", "[out]",
        "-ac", "1", "-ar", "16000",
        path,
    ], capture_output=True, check=True)
    return path


def test_detect_pauses_finds_silence(speech_then_silence_wav) -> None:
    pytest.importorskip("librosa")
    import audio_features
    pauses = audio_features.detect_pauses(speech_then_silence_wav, min_pause=0.5)
    assert len(pauses) >= 1
    assert any(p["duration"] >= 1.5 for p in pauses)


def test_voice_profile_returns_expected_keys(synth_wav) -> None:
    pytest.importorskip("librosa")
    import audio_features
    p = audio_features.voice_profile(synth_wav)
    for k in ("pitch_hz_median", "estimated_gender", "estimated_age_range"):
        assert k in p


def test_voice_profile_440hz_is_female_range(synth_wav) -> None:
    pytest.importorskip("librosa")
    import audio_features
    p = audio_features.voice_profile(synth_wav)
    assert p["estimated_gender"] in ("female", "ambiguous")
    assert 400 <= p["pitch_hz_median"] <= 460


def test_has_background_music_on_pure_tone(synth_wav) -> None:
    pytest.importorskip("librosa")
    import audio_features
    result = audio_features.has_background_music(synth_wav)
    assert "present" in result
    assert "confidence" in result


def test_detect_breath_before_does_not_crash(synth_wav) -> None:
    pytest.importorskip("librosa")
    import audio_features
    audio_features.detect_breath_before(synth_wav, line_start=0.5)


def test_detect_action_complete_static_returns_zero(tmp_path) -> None:
    """完全静止動画は最初の窓で idle と判定される（t=0）。"""
    pytest.importorskip("cv2")
    import audio_features
    path = str(tmp_path / "static.mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=black:size=320x240:rate=30:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
        path,
    ], capture_output=True, check=True)
    t = audio_features.detect_action_complete(
        path, motion_threshold=0.001, min_idle_duration=0.3,
    )
    assert t == 0.0


def test_detect_action_complete_returns_none_when_no_cv2(monkeypatch, tmp_path) -> None:
    import audio_features
    import builtins
    real_import = builtins.__import__

    def block_cv2(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_cv2)
    fake = tmp_path / "x.mp4"
    fake.write_bytes(b"x")
    assert audio_features.detect_action_complete(str(fake)) is None


def test_detect_action_complete_invalid_path_returns_none(tmp_path) -> None:
    pytest.importorskip("cv2")
    import audio_features
    fake = tmp_path / "doesnotexist.mp4"
    assert audio_features.detect_action_complete(str(fake)) is None
