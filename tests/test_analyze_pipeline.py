"""analyze.pipeline.run() の単体テスト。"""
from unittest.mock import patch

import pytest

from analyze import AnalyzeCancelled, AnalyzeOptions, default_output_path
from analyze.pipeline import run


def test_options_to_dict_round_trip() -> None:
    opt = AnalyzeOptions(fps=3.0, instructions="hi",
                          no_bgm_extract=True, no_shots=False)
    d = opt.to_dict()
    assert d == {
        "fps": 3.0,
        "instructions": "hi",
        "no_bgm_extract": True,
        "no_shots": False,
    }
    assert AnalyzeOptions.from_dict(d) == opt


def test_options_from_dict_ignores_unknown_keys() -> None:
    opt = AnalyzeOptions.from_dict({"fps": 1.5, "unknown_key": "x"})
    assert opt.fps == 1.5
    assert opt.instructions is None


def test_default_output_path_sanitizes_special_chars() -> None:
    p = default_output_path("/tmp/サンプル video.mov")
    assert p.endswith("auto_サンプル_video.json")


def test_run_raises_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        run(video_path="/nonexistent/video.mov")


def test_run_raises_cancelled_after_first_phase(tmp_path) -> None:
    fake_video = tmp_path / "v.mov"
    fake_video.write_bytes(b"fake")
    output = tmp_path / "out.json"

    events: list[tuple[str, dict]] = []

    def on_progress(event: str, data: dict) -> None:
        events.append((event, data))

    with patch("analyze.pipeline._extract_frames", return_value=["f1.jpg"]):
        with pytest.raises(AnalyzeCancelled):
            run(
                video_path=str(fake_video),
                output_path=str(output),
                cancel_token=lambda: True,
                on_progress=on_progress,
            )

    # frames だけは完了している (cancel チェックは phase_complete 後)
    assert any(e == "phase_start" and d["phase"] == "frames" for e, d in events)
    assert any(e == "phase_complete" and d["phase"] == "frames" for e, d in events)
    # claude フェーズには到達していない
    assert not any(e == "phase_start" and d["phase"] == "claude" for e, d in events)


def test_run_emits_phase_skipped_for_silent_video(tmp_path) -> None:
    """silent モード + no_shots + no_bgm_extract で全 skip が phase_skipped を発火する。"""
    fake_video = tmp_path / "v.mov"
    fake_video.write_bytes(b"silent")

    skipped: list[str] = []

    def on_progress(event: str, data: dict) -> None:
        if event == "phase_skipped":
            skipped.append(data.get("phase", ""))

    # cost_gate で False を返して Claude 呼び出し前で AnalyzeCancelled。
    with patch("analyze.pipeline._extract_frames", return_value=["f1.jpg"]), \
         patch("analyze.pipeline._has_audio_stream", return_value=False), \
         patch("analyze.pipeline._cache.file_sha256", return_value="v" * 64), \
         patch("analyze.pipeline.furigana_store.load", return_value={}):
        with pytest.raises(AnalyzeCancelled):
            run(
                video_path=str(fake_video),
                output_path=str(tmp_path / "out.json"),
                options=AnalyzeOptions(no_shots=True, no_bgm_extract=True),
                on_progress=on_progress,
                on_cost_gate=lambda *args: False,
                use_cache=False,
            )

    # silent 由来 4 個 + no_shots 1 個 + bgm_separate (音声なし) 1 個
    expected = {"audio", "whisper", "acoustic", "bgm_detect",
                "shots", "bgm_separate"}
    assert expected.issubset(set(skipped))


def test_run_emits_phase_skipped_for_no_shots_only(tmp_path) -> None:
    """音声あり + no_shots のみ → shots だけ skipped、他は通常実行が試みられる。"""
    fake_video = tmp_path / "v.mov"
    fake_video.write_bytes(b"audio")

    skipped: list[str] = []

    def on_progress(event: str, data: dict) -> None:
        if event == "phase_skipped":
            skipped.append(data.get("phase", ""))

    with patch("analyze.pipeline._extract_frames", return_value=["f1.jpg"]), \
         patch("analyze.pipeline._has_audio_stream", return_value=False), \
         patch("analyze.pipeline._cache.file_sha256", return_value="v" * 64), \
         patch("analyze.pipeline.furigana_store.load", return_value={}):
        with pytest.raises(AnalyzeCancelled):
            run(
                video_path=str(fake_video),
                output_path=str(tmp_path / "out.json"),
                options=AnalyzeOptions(no_shots=True),
                on_progress=on_progress,
                on_cost_gate=lambda *args: False,
                use_cache=False,
            )

    assert "shots" in skipped


def test_ensure_min_duration_adjusts_short_scenes() -> None:
    from analyze.pipeline import _ensure_min_duration
    sp = {
        "scenes": [
            {"duration": 2, "lines": [{"text": "a", "start": 0, "end": 1.5}]},
            {"duration": 5, "lines": [{"text": "b", "start": 0, "end": 4}]},
            {"duration": 1.0, "lines": []},
        ],
    }
    n = _ensure_min_duration(sp, min_sec=3.0)
    assert n == 2
    assert sp["scenes"][0]["duration"] == 3.0
    assert sp["scenes"][1]["duration"] == 5
    assert sp["scenes"][2]["duration"] == 3.0


def test_ensure_min_duration_clamps_line_endpoints() -> None:
    from analyze.pipeline import _ensure_min_duration
    sp = {
        "scenes": [
            {
                "duration": 2,
                "lines": [
                    {"text": "x", "start": 0, "end": 5.0},
                    {"text": "y", "start": 4.0, "end": 4.5},
                ],
            },
        ],
    }
    _ensure_min_duration(sp, min_sec=3.0)
    assert sp["scenes"][0]["duration"] == 3.0
    assert sp["scenes"][0]["lines"][0]["end"] == 3.0
    assert sp["scenes"][0]["lines"][1]["start"] == 3.0
    assert sp["scenes"][0]["lines"][1]["end"] == 3.0


def test_ensure_min_duration_noop_for_valid_screenplay() -> None:
    from analyze.pipeline import _ensure_min_duration
    sp = {"scenes": [{"duration": 4}, {"duration": 3.0}]}
    n = _ensure_min_duration(sp, min_sec=3.0)
    assert n == 0
    assert sp["scenes"][0]["duration"] == 4
    assert sp["scenes"][1]["duration"] == 3.0


def test_run_progress_callback_exception_is_swallowed(tmp_path) -> None:
    """progress callback が例外を出してもパイプライン全体は壊れない。"""
    fake_video = tmp_path / "v.mov"
    fake_video.write_bytes(b"fake")

    def bad_callback(event: str, data: dict) -> None:
        raise RuntimeError("callback broken")

    with patch("analyze.pipeline._extract_frames", return_value=["f1.jpg"]):
        # cancel_token を即 True にして frames 後で停止
        with pytest.raises(AnalyzeCancelled):
            run(
                video_path=str(fake_video),
                output_path=str(tmp_path / "out.json"),
                on_progress=bad_callback,
                cancel_token=lambda: True,
            )
