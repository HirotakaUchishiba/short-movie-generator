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


def test_compute_safe_final_duration_capped_at_kling() -> None:
    final = scene_gen._compute_safe_final_duration(
        target_duration=8.0, kling_duration=5.0,
        action_complete=None, tts_total_end=2.0,
    )
    assert final <= 5.0


def test_augment_animation_prompt_adds_settle_instruction() -> None:
    out = scene_gen._augment_animation_prompt("subject walks forward", 5.0)
    assert "Complete all major actions" in out
    assert "70%" in out


def test_augment_animation_prompt_idempotent() -> None:
    base = "subject walks"
    once = scene_gen._augment_animation_prompt(base, 5.0)
    twice = scene_gen._augment_animation_prompt(once, 5.0)
    assert once == twice


def test_augment_animation_prompt_appends_negative_constraint() -> None:
    """UI hallucination 抑止 negative 文が末尾に追加されること。"""
    out = scene_gen._augment_animation_prompt("subject walks forward", 5.0)
    assert scene_gen.config.KLING_NEGATIVE_CONSTRAINT in out
    assert "no UI overlays" in out
    assert "no chat bubbles" in out


def test_augment_animation_prompt_negative_idempotent() -> None:
    """negative 文が既にあれば二重追加しないこと (冪等)。"""
    base = "subject walks"
    once = scene_gen._augment_animation_prompt(base, 5.0)
    # 2 回目: 同じ入力なら同じ出力 (settle / negative どちらも重複なし)
    twice = scene_gen._augment_animation_prompt(once, 5.0)
    assert once == twice
    # 同じ negative 文が 1 回しか出現しない
    assert once.count(scene_gen.config.KLING_NEGATIVE_CONSTRAINT) == 1


def test_augment_animation_prompt_negative_skipped_if_empty(monkeypatch) -> None:
    """KLING_NEGATIVE_CONSTRAINT が空なら追加しない。"""
    monkeypatch.setattr(scene_gen.config, "KLING_NEGATIVE_CONSTRAINT", "")
    out = scene_gen._augment_animation_prompt("subject walks", 5.0)
    assert "no UI overlays" not in out


def test_augment_animation_prompt_preserves_user_text() -> None:
    """ユーザーが書いた本文部分は改変されない。"""
    base = "Young woman leans toward laptop, eyes searching, then exhales"
    out = scene_gen._augment_animation_prompt(base, 5.0)
    assert out.startswith(base)


