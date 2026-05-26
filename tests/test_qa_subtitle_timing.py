"""Phase 2: subtitle_timing validator の単体テスト。

char_ts (tts_full.json) はモックで与える。build_screenplay_text が組む
full_text に対して各文字へ等間隔の timestamp を振り、実発話長を制御する。
"""
from __future__ import annotations

import json

from stages.text_mapping import build_screenplay_text


def _write_char_ts(tmp_path, full_text: str, total_dur: float):
    """full_text の各文字に等間隔 timestamp を振って tts_full.json を書く。"""
    n = len(full_text)
    step = total_dur / n if n else 0.0
    char_ts = [
        {"char": c, "start": i * step, "end": (i + 1) * step}
        for i, c in enumerate(full_text)
    ]
    (tmp_path / "tts_full.json").write_text(
        json.dumps(char_ts, ensure_ascii=False), encoding="utf-8")


def _sp(start: float, end: float, text: str = "こんにちは", speaker=None):
    line = {"text": text, "start": start, "end": end}
    if speaker is not None:
        line["speaker"] = speaker
    return {"scenes": [{"lines": [line]}]}


def test_passes_when_window_matches_speech(tmp_path):
    sp = _sp(0.0, 2.0)
    full_text, _ = build_screenplay_text(sp)
    _write_char_ts(tmp_path, full_text, total_dur=2.0)  # ratio ≈ 1.0
    from qa.validators.subtitle_timing import check_subtitle_timing
    results = check_subtitle_timing(str(tmp_path), screenplay=sp)
    assert len(results) == 1
    assert results[0].passed
    assert abs(results[0].metrics["ratio"] - 1.0) < 0.05


def test_flags_window_far_shorter_than_speech(tmp_path):
    sp = _sp(0.0, 0.4)  # window 0.4s
    full_text, _ = build_screenplay_text(sp)
    _write_char_ts(tmp_path, full_text, total_dur=2.0)  # speech 2.0s → ratio 0.2
    from qa.validators.subtitle_timing import check_subtitle_timing
    results = check_subtitle_timing(str(tmp_path), screenplay=sp)
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].tag == "subtitle_timing_off"
    assert results[0].scene_idx == 0
    assert results[0].line_idx == 0


def test_flags_window_far_longer_than_speech(tmp_path):
    sp = _sp(0.0, 8.0)  # window 8.0s
    full_text, _ = build_screenplay_text(sp)
    _write_char_ts(tmp_path, full_text, total_dur=2.0)  # speech 2.0s → ratio 4.0
    from qa.validators.subtitle_timing import check_subtitle_timing
    results = check_subtitle_timing(str(tmp_path), screenplay=sp)
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].tag == "subtitle_timing_off"


def test_skips_when_no_char_ts(tmp_path):
    sp = _sp(0.0, 2.0)
    from qa.validators.subtitle_timing import check_subtitle_timing
    results = check_subtitle_timing(str(tmp_path), screenplay=sp)
    assert results == []


def test_skips_per_voice_multiple_speakers(tmp_path):
    sp = {
        "scenes": [
            {"lines": [
                {"text": "おはよう", "start": 0.0, "end": 1.0, "speaker": "f1"},
                {"text": "やあ", "start": 1.0, "end": 2.0, "speaker": "m1"},
            ]},
        ],
    }
    full_text, _ = build_screenplay_text(sp)
    _write_char_ts(tmp_path, full_text, total_dur=3.0)
    from qa.validators.subtitle_timing import check_subtitle_timing
    results = check_subtitle_timing(str(tmp_path), screenplay=sp)
    assert results == []


def test_skips_line_without_start_end(tmp_path):
    sp = {"scenes": [{"lines": [{"text": "こんにちは"}]}]}  # start/end 無し
    full_text, _ = build_screenplay_text(sp)
    _write_char_ts(tmp_path, full_text, total_dur=2.0)
    from qa.validators.subtitle_timing import check_subtitle_timing
    results = check_subtitle_timing(str(tmp_path), screenplay=sp)
    assert results == []


def test_char_ts_gap_yields_skipped_pass(tmp_path):
    sp = _sp(0.0, 2.0)
    # char_ts を空にして全文字 gap (= timestamp 無し) を作る。
    (tmp_path / "tts_full.json").write_text("[]", encoding="utf-8")
    from qa.validators.subtitle_timing import check_subtitle_timing
    results = check_subtitle_timing(str(tmp_path), screenplay=sp)
    assert len(results) == 1
    assert results[0].passed  # skipped_result は passed=True
    assert "gap" in results[0].reason


def test_returns_empty_without_screenplay(tmp_path):
    _write_char_ts(tmp_path, "こんにちは", total_dur=2.0)
    from qa.validators.subtitle_timing import check_subtitle_timing
    assert check_subtitle_timing(str(tmp_path), screenplay=None) == []


def test_skips_hidden_line(tmp_path):
    # hidden 行は発話されるが字幕に焼かれないので timing 検査の対象外。
    sp = {"scenes": [{"lines": [
        {"text": "こんにちは", "start": 0.0, "end": 0.4, "hidden": True}]}]}
    full_text, _ = build_screenplay_text(sp)
    _write_char_ts(tmp_path, full_text, total_dur=2.0)  # ratio 0.2 だが hidden
    from qa.validators.subtitle_timing import check_subtitle_timing
    assert check_subtitle_timing(str(tmp_path), screenplay=sp) == []
