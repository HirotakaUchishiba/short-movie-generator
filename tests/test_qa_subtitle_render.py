"""Phase 2: subtitle_render validator の単体テスト。

実 OCR は環境依存 (tesseract) なので、成果物の有無と依存欠落時の skip を検証する。
"""
from __future__ import annotations

from unittest.mock import patch


def _sp():
    return {"scenes": [{"lines": [{"text": "字幕", "start": 0.0, "end": 1.0}]}]}


def test_returns_empty_without_overlaid(tmp_path):
    from qa.validators.subtitle_render import check_subtitle_render
    assert check_subtitle_render(str(tmp_path), screenplay=_sp()) == []


def test_deps_missing_is_skipped(tmp_path):
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch("qa.validators.subtitle_render._check_deps",
               return_value=(False, "tesseract binary not found")):
        from qa.validators.subtitle_render import check_subtitle_render
        r = check_subtitle_render(str(tmp_path), screenplay=_sp())
    assert len(r) == 1
    assert r[0].passed  # skipped_result
    assert "tesseract" in r[0].reason


def test_frame_extraction_failure_is_skipped(tmp_path):
    import pytest
    pytest.importorskip("pytesseract")
    pytest.importorskip("PIL")
    (tmp_path / "overlaid.mp4").write_bytes(b"x")
    with patch("qa.validators.subtitle_render._check_deps",
               return_value=(True, "ok")), \
         patch("qa.validators.subtitle_render._extract_frame",
               return_value=False):
        from qa.validators.subtitle_render import check_subtitle_render
        r = check_subtitle_render(str(tmp_path), screenplay=_sp())
    assert len(r) == 1
    assert r[0].passed  # skipped
    assert "frame" in r[0].reason
