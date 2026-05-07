"""Phase 2: 各 validator の単体テスト。

外部 IO (ffmpeg / librosa / CLIP / opencv) は patch / skip で扱う。
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def _stub_ffmpeg(text: str):
    class _Proc:
        stderr = text
        stdout = ""
        returncode = 0
    return _Proc()


# ─── audio_silence ──────────────────────────────────────────


def test_audio_silence_returns_per_line_results(tmp_path):
    (tmp_path / "tts_0_0.mp3").write_bytes(b"x")
    (tmp_path / "tts_0_1.mp3").write_bytes(b"x")
    text_ok = """
  Duration: 00:00:5.0, bitrate: 96 kb/s
[Parsed_volumedetect_0 @ 0x] mean_volume: -22.0 dB
"""
    with patch("subprocess.run", return_value=_stub_ffmpeg(text_ok)):
        from qa.validators.audio_silence import check_audio_silence
        results = check_audio_silence(str(tmp_path))
    assert len(results) == 2
    assert all(r.passed for r in results)
    assert {(r.scene_idx, r.line_idx) for r in results} == {(0, 0), (0, 1)}


def test_audio_silence_flags_silent_line(tmp_path):
    (tmp_path / "tts_3_2.mp3").write_bytes(b"x")
    text_silent = """
  Duration: 00:00:10.0, bitrate: 96 kb/s
[Parsed_volumedetect_0 @ 0x] mean_volume: -55.0 dB
"""
    with patch("subprocess.run", return_value=_stub_ffmpeg(text_silent)):
        from qa.validators.audio_silence import check_audio_silence
        results = check_audio_silence(str(tmp_path))
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].tag == "audio_silence"
    assert results[0].scene_idx == 3
    assert results[0].line_idx == 2


# ─── audio_clipping ──────────────────────────────────────────


def test_audio_clipping_fallback_to_ffmpeg(tmp_path):
    (tmp_path / "tts_0_0.mp3").write_bytes(b"x")
    text = """
  Duration: 00:00:5.0
[Parsed_volumedetect_0 @ 0x] max_volume: 1.5 dB
"""
    # librosa を ImportError にして ffmpeg fallback を強制
    with patch("subprocess.run", return_value=_stub_ffmpeg(text)):
        from qa.validators import audio_clipping
        with patch.object(audio_clipping, "_peak_dbfs_via_librosa",
                          side_effect=ImportError("no librosa")):
            results = audio_clipping.check_audio_clipping(str(tmp_path))
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].tag == "audio_clipping"
    assert results[0].metrics["peak_dbfs"] == pytest.approx(1.5)


def test_audio_clipping_passes_below_threshold(tmp_path):
    (tmp_path / "tts_1_0.mp3").write_bytes(b"x")
    text = """
  Duration: 00:00:5.0
[Parsed_volumedetect_0 @ 0x] max_volume: -3.0 dB
"""
    with patch("subprocess.run", return_value=_stub_ffmpeg(text)):
        from qa.validators import audio_clipping
        with patch.object(audio_clipping, "_peak_dbfs_via_librosa",
                          side_effect=ImportError("no librosa")):
            results = audio_clipping.check_audio_clipping(str(tmp_path))
    assert results[0].passed
    assert results[0].metrics["peak_dbfs"] == pytest.approx(-3.0)


# ─── subtitle_overlap ──────────────────────────────────────────


def test_subtitle_overlap_passes_on_uniform_image(tmp_path):
    from PIL import Image
    img = Image.new("RGB", (1080, 1920), color=(40, 40, 40))
    img.save(tmp_path / "bg_0.png")
    from qa.validators.subtitle_overlap import check_subtitle_overlap
    results = check_subtitle_overlap(str(tmp_path))
    assert len(results) == 1
    assert results[0].passed


def test_subtitle_overlap_fails_on_busy_bottom(tmp_path):
    """画像下半分が黒白チェッカーボード (= stddev ≈ 127) で fail。"""
    import numpy as np
    from PIL import Image
    arr = np.zeros((1920, 1080, 3), dtype=np.uint8) + 30
    # 下 1/3 を 0/255 の縞模様 → stddev は 127 前後
    arr[1280:, ::2, :] = 255
    arr[1280:, 1::2, :] = 0
    Image.fromarray(arr).save(tmp_path / "bg_5.png")
    from qa.validators.subtitle_overlap import check_subtitle_overlap
    results = check_subtitle_overlap(str(tmp_path))
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].tag == "subtitle_zone_blocked"
    assert results[0].scene_idx == 5


# ─── subtitle_readability ──────────────────────────────────────────


def test_subtitle_readability_long_chunk_fails():
    from qa.validators.subtitle_readability import check_subtitle_readability
    sp = {"scenes": [{
        "lines": [{"text": "短い"}, {"text": "あ" * 30}],
    }]}
    results = check_subtitle_readability("/x", screenplay=sp)
    assert len(results) == 2
    assert results[0].passed
    assert not results[1].passed
    assert results[1].tag == "subtitle_too_long"
    assert results[1].line_idx == 1


def test_subtitle_readability_uses_subtitle_chunks_when_present():
    from qa.validators.subtitle_readability import check_subtitle_readability
    sp = {"scenes": [{
        "lines": [{
            "text": "とても長いテキストでも subtitles に分割されていれば read しやすい",
            "subtitles": [{"text": "短"}, {"text": "い"}],
        }],
    }]}
    results = check_subtitle_readability("/x", screenplay=sp)
    assert results[0].passed


# ─── story_pacing ──────────────────────────────────────────


def test_story_pacing_skips_lines_without_timing():
    from qa.validators.story_pacing import check_story_pacing
    sp = {"scenes": [{"lines": [{"text": "x"}]}]}
    assert check_story_pacing("/x", screenplay=sp) == []


def test_story_pacing_flags_fast_speech():
    from qa.validators.story_pacing import check_story_pacing
    # 2 秒で 25 文字 → 750 wpm > 600 で fail
    sp = {"scenes": [{"lines": [
        {"text": "あ" * 25, "start": 0.0, "end": 2.0},
    ]}]}
    results = check_story_pacing("/x", screenplay=sp)
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].tag == "story_pacing_off"


def test_story_pacing_passes_normal_speech():
    from qa.validators.story_pacing import check_story_pacing
    # 5 秒で 25 文字 → 300 wpm
    sp = {"scenes": [{"lines": [
        {"text": "あ" * 25, "start": 0.0, "end": 5.0},
    ]}]}
    results = check_story_pacing("/x", screenplay=sp)
    assert results[0].passed


# ─── character_drift / lipsync_quality (= optional dep) ──────────────


def test_character_drift_skipped_when_no_clip(tmp_path):
    (tmp_path / "kling_0.mp4").write_bytes(b"x")
    from qa.validators import character_drift
    with patch.object(character_drift, "_load_clip_model", return_value=None):
        results = character_drift.check_character_drift(
            str(tmp_path), screenplay={"scenes": []},
        )
    assert len(results) == 1
    assert results[0].passed  # skipped はパス扱い
    assert "skipped" in results[0].reason or "unavailable" in results[0].reason


def test_lipsync_quality_skipped_without_dependencies(tmp_path):
    (tmp_path / "scene_0.mp4").write_bytes(b"x")
    from qa.validators import lipsync_quality
    with patch.object(lipsync_quality, "_check_dependencies",
                      return_value=(False, "missing cv2")):
        results = lipsync_quality.check_lipsync_quality(str(tmp_path))
    assert len(results) == 1
    assert results[0].passed
    assert "missing" in results[0].reason or "skipped" in results[0].reason
