"""Phase 2: 各 validator の単体テスト。

外部 IO (ffmpeg / librosa / CLIP / opencv) は patch / skip で扱う。
"""
from __future__ import annotations

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


def test_character_drift_reads_refs_from_nested_identity(tmp_path):
    """character_refs は nested identity から読む (= flat schema 撤去後)。"""
    (tmp_path / "kling_0.mp4").write_bytes(b"x")
    from qa.validators import character_drift
    seen_refs: list = []

    def _spy(refs):
        seen_refs.append(list(refs))
        return []  # 空 → scene を skip (= frame 抽出まで進まない)

    with patch.object(character_drift, "_load_clip_model",
                      return_value=object()), \
         patch.object(character_drift, "_resolve_character_ref_paths",
                      side_effect=_spy):
        character_drift.check_character_drift(
            str(tmp_path),
            screenplay={"scenes": [
                {"identity": {"character_refs": ["f1__office"]}},
            ]},
        )
    assert seen_refs == [["f1__office"]]


def test_lipsync_quality_skipped_without_dependencies(tmp_path):
    (tmp_path / "scene_0.mp4").write_bytes(b"x")
    from qa.validators import lipsync_quality
    with patch.object(lipsync_quality, "_check_dependencies",
                      return_value=(False, "missing cv2")):
        results = lipsync_quality.check_lipsync_quality(str(tmp_path))
    assert len(results) == 1
    assert results[0].passed
    assert "missing" in results[0].reason or "skipped" in results[0].reason


# ─── character_drift の cache + 代表フレーム経路 ──────────


def test_character_drift_clip_load_is_memoized(monkeypatch):
    """_load_clip_model の中で sentence_transformers import を 1 度だけ実行する。"""
    from qa.validators import character_drift
    # cache を毎回テスト用に reset
    monkeypatch.setattr(character_drift, "_CLIP_MODEL", None)
    monkeypatch.setattr(character_drift, "_CLIP_LOAD_ATTEMPTED", False)

    call_count = {"n": 0}

    def _fake_import():
        call_count["n"] += 1
        raise ImportError("no sentence_transformers")

    # 内部 import の代わりに、sentence_transformers が無い状態を再現する。
    # _load_clip_model は ImportError を catch して None を cache + 返す想定。
    import sys
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    m1 = character_drift._load_clip_model()
    m2 = character_drift._load_clip_model()
    assert m1 is None
    assert m2 is None
    # 2 回目以降は cache hit (= _CLIP_LOAD_ATTEMPTED=True で短絡)
    assert character_drift._CLIP_LOAD_ATTEMPTED is True


def test_character_drift_extract_representative_frame_seeks_one_second(tmp_path,
                                                                       monkeypatch):
    """_extract_representative_frame は 1.0s 地点を試みる。"""
    from qa.validators import character_drift
    seek_args: list[str] = []

    def _fake_run(args, **kwargs):
        # ffmpeg コマンド列の -ss 引数を記録
        if "-ss" in args:
            ss = args[args.index("-ss") + 1]
            seek_args.append(ss)
        # 出力ファイルを実際に作って成功扱いにする
        out_path = args[-1]
        with open(out_path, "wb") as f:
            f.write(b"\x89PNG")
        class _Proc:
            returncode = 0
        return _Proc()

    monkeypatch.setattr("subprocess.run", _fake_run)
    out = tmp_path / "frame.png"
    ok = character_drift._extract_representative_frame(
        str(tmp_path / "kling_0.mp4"), str(out),
    )
    assert ok is True
    assert seek_args[0].startswith("00:00:01")  # 1s 地点を最初に試行
