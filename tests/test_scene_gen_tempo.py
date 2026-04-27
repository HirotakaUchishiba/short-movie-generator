import pytest

import scene_gen


def _line(text: str = "x", start: float = 0.0) -> dict:
    return {"text": text, "start": start}


def test_tempo_max_no_lines() -> None:
    assert scene_gen._tempo_max_for_scene({"lines": []}) == scene_gen.config.TEMPO_MAX_NO_LINES


def test_tempo_max_single_short_line() -> None:
    assert scene_gen._tempo_max_for_scene({
        "lines": [_line("短いセリフ")],
    }) == scene_gen.config.TEMPO_MAX_SINGLE_LINE


def test_tempo_max_two_lines() -> None:
    assert scene_gen._tempo_max_for_scene({
        "lines": [_line("a"), _line("b")],
    }) == scene_gen.config.TEMPO_MAX_MULTI_LINE


def test_tempo_max_three_lines() -> None:
    assert scene_gen._tempo_max_for_scene({
        "lines": [_line("a"), _line("b"), _line("c")],
    }) == scene_gen.config.TEMPO_MAX_LONG_TEXT


def test_tempo_max_long_single_line_treated_as_multi() -> None:
    long = "あ" * 30
    assert scene_gen._tempo_max_for_scene({
        "lines": [_line(long)],
    }) == scene_gen.config.TEMPO_MAX_MULTI_LINE


def test_tempo_max_very_long_text_uses_long_ceiling() -> None:
    very_long = "あ" * 60
    assert scene_gen._tempo_max_for_scene({
        "lines": [_line(very_long)],
    }) == scene_gen.config.TEMPO_MAX_LONG_TEXT


def test_compute_target_duration_uses_floor_not_tempo_max() -> None:
    """テンポ規範緩和: floorをそのまま採用する（自然な発話優先）。"""
    target = scene_gen._compute_target_duration({"lines": [_line("a")]}, tts_total_end=2.0)
    assert target == scene_gen.config.SCENE_MIN_DURATION


def test_compute_target_duration_floor_overrides_tempo() -> None:
    target = scene_gen._compute_target_duration(
        {"lines": [_line("a")]}, tts_total_end=10.0,
    )
    assert target == 10.0


def test_compute_target_duration_warns_when_exceeding_tempo_max(caplog) -> None:
    import logging
    with caplog.at_level(logging.WARNING, logger="scene_gen"):
        scene_gen._compute_target_duration(
            {"lines": [_line("a")]}, tts_total_end=10.0,
        )
    assert any("テンポ規範超過" in rec.message for rec in caplog.records)


def test_compute_target_duration_minimum_is_kling_min() -> None:
    target = scene_gen._compute_target_duration({"lines": []}, tts_total_end=0)
    assert target >= scene_gen.config.SCENE_MIN_DURATION


def test_compute_safe_final_duration_uses_action_complete_when_safe() -> None:
    final = scene_gen._compute_safe_final_duration(
        target_duration=5.0, kling_duration=5.0,
        action_complete=3.5, tts_total_end=3.0,
    )
    assert final == 3.5


def test_compute_safe_final_duration_respects_audio_floor() -> None:
    final = scene_gen._compute_safe_final_duration(
        target_duration=3.0, kling_duration=5.0,
        action_complete=2.0, tts_total_end=4.5,
    )
    assert final >= 4.5


def test_compute_safe_final_duration_no_action_complete() -> None:
    final = scene_gen._compute_safe_final_duration(
        target_duration=5.0, kling_duration=5.0,
        action_complete=None, tts_total_end=2.0,
    )
    assert final == 5.0


def test_compute_safe_final_duration_allows_exceeding_kling_for_tts() -> None:
    """TTS が kling 尺を超える場合、cap せず TTS 尺を採用する
    (動画は後段で slow_mo 延長して合わせる)。"""
    final = scene_gen._compute_safe_final_duration(
        target_duration=5.0, kling_duration=5.0,
        action_complete=None, tts_total_end=6.5,
    )
    assert final == 6.5


def test_compute_safe_final_duration_action_complete_above_kling_ignored() -> None:
    """action_complete が kling_duration を超える場合は採用しない。"""
    final = scene_gen._compute_safe_final_duration(
        target_duration=5.0, kling_duration=5.0,
        action_complete=6.0, tts_total_end=2.0,
    )
    assert final == 5.0


def test_compute_safe_final_duration_target_within_kling() -> None:
    """target_duration が kling 内なら従来通り target を返す。"""
    final = scene_gen._compute_safe_final_duration(
        target_duration=4.0, kling_duration=5.0,
        action_complete=None, tts_total_end=2.0,
    )
    assert final == 4.0


def test_augment_animation_prompt_adds_settle_instruction() -> None:
    out = scene_gen._augment_animation_prompt("subject walks forward", 5.0)
    assert "Complete all major actions" in out
    assert "70%" in out


def test_augment_animation_prompt_idempotent() -> None:
    base = "subject walks"
    once = scene_gen._augment_animation_prompt(base, 5.0)
    twice = scene_gen._augment_animation_prompt(once, 5.0)
    assert once == twice


