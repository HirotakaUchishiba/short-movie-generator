"""Phase 2: subtitle_audio_sync validator の単体テスト。

whisper_client.transcribe をモックして ref カバレッジ判定を検証する。
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


def test_full_coverage_passes(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch("whisper_client.transcribe",
               return_value={"text": "こんにちは、世界。", "words": []}):
        from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
        r = check_subtitle_audio_sync(str(tmp_path), screenplay=_sp())
    assert len(r) == 1 and r[0].passed
    assert r[0].metrics["coverage"] > 0.9


def test_longer_transcript_still_passes(tmp_path):
    # 字幕が完全発話されていれば transcript が長くても pass
    # (= difflib 対称性バグの回帰防止)
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    long_hyp = "こんにちは世界" + "それからとても長いナレーションが続きますよ" * 3
    with patch("whisper_client.transcribe",
               return_value={"text": long_hyp, "words": []}):
        from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
        r = check_subtitle_audio_sync(str(tmp_path), screenplay=_sp())
    assert len(r) == 1 and r[0].passed
    assert r[0].metrics["coverage"] > 0.9


def test_missing_subtitle_text_fails(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch("whisper_client.transcribe",
               return_value={"text": "まったく別個の発話素材", "words": []}):
        from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
        r = check_subtitle_audio_sync(str(tmp_path), screenplay=_sp())
    assert len(r) == 1 and not r[0].passed
    assert r[0].tag == "audio_mispronounce"


def test_whisper_failure_is_skipped(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch("whisper_client.transcribe", side_effect=RuntimeError("boom")):
        from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
        r = check_subtitle_audio_sync(str(tmp_path), screenplay=_sp())
    assert len(r) == 1 and r[0].passed  # skipped_result は passed=True
    assert "whisper failed" in r[0].reason


def test_non_dict_result_is_skipped(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch("whisper_client.transcribe", return_value=None):
        from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
        r = check_subtitle_audio_sync(str(tmp_path), screenplay=_sp())
    assert len(r) == 1 and r[0].passed
