"""Phase 1 暫定 validator (silence / 黒フレーム) の単体テスト。

ffmpeg は subprocess.run を patch して、stderr テキストでパス / fail の
両方をシミュレートする。"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _stub_ffmpeg(text: str):
    class _Proc:
        stderr = text
        stdout = ""
    return _Proc()


# ─── TTS audio ──────────────────────────────────────────


def test_tts_audio_pass_when_normal():
    text = """
  Duration: 00:00:10.5, bitrate: 96 kb/s
[Parsed_volumedetect_0 @ 0x] mean_volume: -23.5 dB
[Parsed_volumedetect_0 @ 0x] max_volume: -3.4 dB
"""
    with patch("subprocess.run", return_value=_stub_ffmpeg(text)):
        from qa.validators_provisional import check_tts_audio
        r = check_tts_audio("/x.mp3")
    assert r.passed is True
    assert r.metrics["mean_volume_db"] == pytest.approx(-23.5)
    assert r.metrics["silence_ratio"] == 0.0


def test_tts_audio_fail_when_silent():
    text = """
  Duration: 00:00:10.0, bitrate: 96 kb/s
[Parsed_volumedetect_0 @ 0x] mean_volume: -52.5 dB
[Parsed_volumedetect_0 @ 0x] max_volume: -30.0 dB
"""
    with patch("subprocess.run", return_value=_stub_ffmpeg(text)):
        from qa.validators_provisional import check_tts_audio
        r = check_tts_audio("/x.mp3")
    assert r.passed is False
    assert "mean_volume" in r.reason


def test_tts_audio_fail_when_high_silence_ratio():
    # 10 秒のうち 7 秒が silence (= ratio 0.7 > 0.5)
    text = """
  Duration: 00:00:10.0, bitrate: 96 kb/s
[Parsed_volumedetect_0 @ 0x] mean_volume: -20.5 dB
[silencedetect @ 0x] silence_start: 0
[silencedetect @ 0x] silence_end: 4.0 | silence_duration: 4.0
[silencedetect @ 0x] silence_start: 6.0
[silencedetect @ 0x] silence_end: 9.0 | silence_duration: 3.0
"""
    with patch("subprocess.run", return_value=_stub_ffmpeg(text)):
        from qa.validators_provisional import check_tts_audio
        r = check_tts_audio("/x.mp3")
    assert r.passed is False
    assert "silence_ratio" in r.reason
    assert r.metrics["silence_ratio"] == pytest.approx(0.7)


def test_tts_audio_handles_missing_ffmpeg():
    with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg")):
        from qa.validators_provisional import check_tts_audio
        r = check_tts_audio("/x.mp3")
    assert r.passed is False
    assert "ffmpeg failed" in r.reason


# ─── Kling 黒フレーム ──────────────────────────────────────────


def test_kling_passes_when_no_black():
    text = "  Duration: 00:00:5.0, bitrate: 5000 kb/s\n"
    with patch("subprocess.run", return_value=_stub_ffmpeg(text)):
        from qa.validators_provisional import check_kling_blackframes
        r = check_kling_blackframes("/x.mp4")
    assert r.passed is True
    assert r.metrics["black_ratio"] == 0.0


def test_kling_fails_with_majority_black():
    # 5 秒 のうち 4 秒が黒 (= ratio 0.8 > 0.5)
    text = """
  Duration: 00:00:5.0, bitrate: 5000 kb/s
[blackdetect @ 0x] black_start:0 black_end:4 black_duration:4.0
"""
    with patch("subprocess.run", return_value=_stub_ffmpeg(text)):
        from qa.validators_provisional import check_kling_blackframes
        r = check_kling_blackframes("/x.mp4")
    assert r.passed is False
    assert "black_ratio" in r.reason
    assert r.metrics["black_ratio"] == pytest.approx(0.8)


def test_kling_handles_ffmpeg_timeout():
    import subprocess
    with patch("subprocess.run",
               side_effect=subprocess.TimeoutExpired("ffmpeg", 60)):
        from qa.validators_provisional import check_kling_blackframes
        r = check_kling_blackframes("/x.mp4")
    assert r.passed is False
    assert "ffmpeg failed" in r.reason
