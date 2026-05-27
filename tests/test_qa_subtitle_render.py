"""Phase 5: subtitle_render validator の単体テスト。

ffmpeg / opencv 実行は環境依存なので、フレーム抽出・エッジ密度・OCR を mock して
判定ロジックを検証する。実データ動作は scripts/動作確認で別途行う。
"""
from __future__ import annotations

from unittest.mock import patch

_MOD = "qa.validators.subtitle_render"


def _sp():
    return {"scenes": [{"lines": [{"text": "字幕", "start": 0.0, "end": 1.0}]}]}


def test_returns_empty_without_overlaid(tmp_path):
    from qa.validators.subtitle_render import check_subtitle_render
    assert check_subtitle_render(str(tmp_path), screenplay=_sp()) == []


def test_deps_missing_is_skipped(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch(f"{_MOD}._deps_ok", return_value=(False, "opencv missing")):
        from qa.validators.subtitle_render import check_subtitle_render
        r = check_subtitle_render(str(tmp_path), screenplay=_sp())
    assert len(r) == 1 and r[0].passed  # skipped_result
    assert "opencv" in r[0].reason


def test_unknown_duration_is_skipped(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch(f"{_MOD}._deps_ok", return_value=(True, "ok")), \
         patch(f"{_MOD}._video_duration", return_value=0.0):
        from qa.validators.subtitle_render import check_subtitle_render
        r = check_subtitle_render(str(tmp_path), screenplay=_sp())
    assert len(r) == 1 and r[0].passed
    assert "duration" in r[0].reason


def test_low_edge_density_fails(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch(f"{_MOD}._deps_ok", return_value=(True, "ok")), \
         patch(f"{_MOD}._video_duration", return_value=10.0), \
         patch(f"{_MOD}._extract_frame", return_value=True), \
         patch(f"{_MOD}._edge_density_bottom", return_value=0.001), \
         patch(f"{_MOD}._ocr_bottom", return_value=None):
        from qa.validators.subtitle_render import check_subtitle_render
        r = check_subtitle_render(str(tmp_path), screenplay=_sp())
    assert len(r) == 1
    assert not r[0].passed
    assert r[0].tag == "subtitle_off_screen"
    assert r[0].metrics["frames_sampled"] == 4.0


def test_high_edge_density_passes(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch(f"{_MOD}._deps_ok", return_value=(True, "ok")), \
         patch(f"{_MOD}._video_duration", return_value=10.0), \
         patch(f"{_MOD}._extract_frame", return_value=True), \
         patch(f"{_MOD}._edge_density_bottom", return_value=0.08), \
         patch(f"{_MOD}._ocr_bottom", return_value="字幕テキスト"):
        from qa.validators.subtitle_render import check_subtitle_render
        r = check_subtitle_render(str(tmp_path), screenplay=_sp())
    assert len(r) == 1 and r[0].passed
    assert r[0].metrics["ocr_text_found"] == 1.0


def test_all_frames_fail_extraction_is_skipped(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch(f"{_MOD}._deps_ok", return_value=(True, "ok")), \
         patch(f"{_MOD}._video_duration", return_value=10.0), \
         patch(f"{_MOD}._extract_frame", return_value=False):
        from qa.validators.subtitle_render import check_subtitle_render
        r = check_subtitle_render(str(tmp_path), screenplay=_sp())
    assert len(r) == 1 and r[0].passed  # skipped
    assert "frame extraction" in r[0].reason
