"""Phase 2: subtitle_audio_sync validator の単体テスト。

whisper_client.transcribe をモックして文字一致率の判定を検証する。
"""
from __future__ import annotations

from unittest.mock import patch


def _sp(text: str = "こんにちは世界"):
    return {"scenes": [{"lines": [{"text": text, "start": 0.0, "end": 2.0}]}]}


def test_returns_empty_without_overlaid(tmp_path):
    from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
    assert check_subtitle_audio_sync(str(tmp_path), screenplay=_sp()) == []


def test_returns_empty_without_screenplay(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
    assert check_subtitle_audio_sync(str(tmp_path), screenplay=None) == []


def test_high_match_passes(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch("whisper_client.transcribe",
               return_value={"text": "こんにちは、世界。", "words": []}):
        from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
        r = check_subtitle_audio_sync(str(tmp_path), screenplay=_sp())
    assert len(r) == 1
    assert r[0].passed
    assert r[0].metrics["match_ratio"] > 0.9


def test_low_match_fails(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch("whisper_client.transcribe",
               return_value={"text": "まったく異なる発話内容ですよ", "words": []}):
        from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
        r = check_subtitle_audio_sync(str(tmp_path), screenplay=_sp())
    assert len(r) == 1
    assert not r[0].passed
    assert r[0].tag == "subtitle_timing_off"


def test_whisper_failure_is_skipped(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch("whisper_client.transcribe", side_effect=RuntimeError("boom")):
        from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
        r = check_subtitle_audio_sync(str(tmp_path), screenplay=_sp())
    assert len(r) == 1
    assert r[0].passed  # skipped_result は passed=True
    assert "whisper failed" in r[0].reason
