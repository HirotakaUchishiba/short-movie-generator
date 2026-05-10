"""analyze.pipeline.run() の単体テスト。"""
from unittest.mock import patch

import pytest

from analyze import AnalyzeCancelled, AnalyzeOptions, default_output_path
from analyze.pipeline import run


def test_options_to_dict_round_trip() -> None:
    opt = AnalyzeOptions(fps=3.0, instructions="hi")
    d = opt.to_dict()
    assert d == {"fps": 3.0, "instructions": "hi"}
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
    """silent モード (音声なし) で audio/whisper/acoustic が phase_skipped を発火。"""
    fake_video = tmp_path / "v.mov"
    fake_video.write_bytes(b"silent")

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
                options=AnalyzeOptions(),
                on_progress=on_progress,
                on_cost_gate=lambda *args: False,
                use_cache=False,
            )

    expected = {"audio", "whisper", "acoustic"}
    assert expected.issubset(set(skipped))


def test_downsample_frames_noop_when_under_limit() -> None:
    from analyze.pipeline import _downsample_frames
    paths = [f"f{i}.jpg" for i in range(50)]
    assert _downsample_frames(paths, max_frames=100) == paths


def test_downsample_frames_keeps_first_and_last() -> None:
    from analyze.pipeline import _downsample_frames
    paths = [f"f{i:04d}.jpg" for i in range(202)]
    out = _downsample_frames(paths, max_frames=100)
    assert len(out) == 100
    assert out[0] == "f0000.jpg"
    assert out[-1] == "f0201.jpg"
    # 単調増加 (順序維持)
    indices = [int(p.removeprefix("f").removesuffix(".jpg")) for p in out]
    assert indices == sorted(indices)


def test_downsample_frames_uniform_spacing() -> None:
    from analyze.pipeline import _downsample_frames
    paths = [f"f{i:04d}.jpg" for i in range(200)]
    out = _downsample_frames(paths, max_frames=10)
    indices = [int(p.removeprefix("f").removesuffix(".jpg")) for p in out]
    # 約 22 ずつ間隔で並ぶ (199/9 ≈ 22.1)
    diffs = [indices[i + 1] - indices[i] for i in range(len(indices) - 1)]
    assert max(diffs) - min(diffs) <= 1  # 等間隔 (誤差 ±1)


def test_normalize_scene_pronunciation_hints_merges_into_lines() -> None:
    from analyze.pipeline import _normalize_scene_pronunciation_hints
    sp = {
        "scenes": [
            {
                "duration": 5,
                "pronunciation_hints": {"AWS": "エーダブリューエス", "IT": "アイティー"},
                "lines": [
                    {"text": "AWS は便利"},
                    {"text": "IT 業界",
                     "pronunciation_hints": {"IT": "アイティ"}},  # line 個別優先
                ],
            },
            {"duration": 3, "lines": [{"text": "x"}]},  # hints 無し
        ],
    }
    n = _normalize_scene_pronunciation_hints(sp)
    assert n == 1
    # scene 直下から削除されている
    assert "pronunciation_hints" not in sp["scenes"][0]
    # line[0] には scene 由来 hints が展開
    assert sp["scenes"][0]["lines"][0]["pronunciation_hints"] == {
        "AWS": "エーダブリューエス", "IT": "アイティー",
    }
    # line[1] は個別指定の "IT" → "アイティ" が優先される
    assert sp["scenes"][0]["lines"][1]["pronunciation_hints"] == {
        "AWS": "エーダブリューエス", "IT": "アイティ",
    }
    # hints 無し scene は無変更
    assert "pronunciation_hints" not in sp["scenes"][1]


def test_normalize_scene_pronunciation_hints_noop_for_clean_screenplay() -> None:
    from analyze.pipeline import _normalize_scene_pronunciation_hints
    sp = {"scenes": [{"duration": 3, "lines": [{"text": "x"}]}]}
    assert _normalize_scene_pronunciation_hints(sp) == 0


def test_summarize_annotation_stats_counts_hit_and_demoted() -> None:
    from analyze.pipeline import _summarize_annotation_stats
    sp = {
        "scenes": [
            # hit
            {"annotation": {"visual_intent_id": "talking_head_calm",
                             "duration_bucket": 5}},
            # hit (同 id)
            {"annotation": {"visual_intent_id": "talking_head_calm"}},
            # hit (別 id)
            {"annotation": {"visual_intent_id": "reaction_surprise",
                             "motion_intensity": "high"}},
            # demoted: annotation 自体が無い
            {"duration": 3, "lines": []},
            # demoted: annotation はあるが visual_intent_id 無し
            {"annotation": {"duration_bucket": 10, "motion_intensity": "low"}},
        ],
    }
    stats = _summarize_annotation_stats(sp)
    assert stats == {
        "total_scenes": 5,
        "with_visual_intent_id": 3,
        "low_confidence_demoted": 2,
        "by_intent_id": {
            "talking_head_calm": 2,
            "reaction_surprise": 1,
        },
    }


def test_summarize_annotation_stats_empty_screenplay() -> None:
    from analyze.pipeline import _summarize_annotation_stats
    assert _summarize_annotation_stats({}) == {
        "total_scenes": 0,
        "with_visual_intent_id": 0,
        "low_confidence_demoted": 0,
        "by_intent_id": {},
    }


def test_summarize_annotation_stats_all_demoted() -> None:
    from analyze.pipeline import _summarize_annotation_stats
    sp = {"scenes": [{"duration": 1}, {"duration": 2}]}
    stats = _summarize_annotation_stats(sp)
    assert stats["total_scenes"] == 2
    assert stats["with_visual_intent_id"] == 0
    assert stats["low_confidence_demoted"] == 2
    assert stats["by_intent_id"] == {}


def test_run_emits_annotation_stats_in_phase_complete_save(tmp_path) -> None:
    """phase_complete:save event に annotation_stats が乗ることを保証。"""
    fake_video = tmp_path / "v.mov"
    fake_video.write_bytes(b"fake")
    output = tmp_path / "out.json"

    events: list[tuple[str, dict]] = []

    def on_progress(event: str, data: dict) -> None:
        events.append((event, dict(data)))

    fake_screenplay = {
        "caption": "x",
        "scenes": [
            {"annotation": {"visual_intent_id": "talking_head_calm"},
             "lines": [{"text": "a", "start": 0.0, "end": 1.0}]},
            {"annotation": {"visual_intent_id": "talking_head_calm"},
             "lines": [{"text": "b", "start": 0.0, "end": 1.0}]},
            # demoted: visual_intent_id 無し
            {"annotation": {"duration_bucket": 5},
             "lines": [{"text": "c", "start": 0.0, "end": 1.0}]},
            # demoted: annotation 自体無し
            {"lines": [{"text": "d", "start": 0.0, "end": 1.0}]},
        ],
    }

    with patch("analyze.pipeline._extract_frames", return_value=["f1.jpg"]), \
         patch("analyze.pipeline._has_audio_stream", return_value=False), \
         patch("analyze.pipeline._cache.file_sha256", return_value="v" * 64), \
         patch("analyze.pipeline.furigana_store.load", return_value={}), \
         patch("analyze.pipeline.furigana_store.collect_from_screenplay",
               return_value={}), \
         patch("analyze.pipeline.load_intent_catalog", return_value=[]), \
         patch("analyze.pipeline.build_screenplay",
               return_value=(fake_screenplay,
                             {"input_tokens": 0, "output_tokens": 0})):
        run(
            video_path=str(fake_video),
            output_path=str(output),
            on_progress=on_progress,
            use_cache=False,
        )

    save_events = [d for e, d in events
                   if e == "phase_complete" and d.get("phase") == "save"]
    assert len(save_events) == 1
    stats = save_events[0]["annotation_stats"]
    assert stats == {
        "total_scenes": 4,
        "with_visual_intent_id": 2,
        "low_confidence_demoted": 2,
        "by_intent_id": {"talking_head_calm": 2},
    }


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
