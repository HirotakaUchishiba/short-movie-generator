import pytest

import screenplay_validator


def _valid_screenplay() -> dict:
    return {
        "caption": "会社選びが何より大切です\n\n#未経験 #転職",
        "scenes": [
            {
                "time": "9:00",
                "label": "始業",
                "duration": 5.0,
                "background_prompt": "オフィスで考え込む男性 cinematic lighting",
                "animation_prompt": "slow zoom",
                "lines": [
                    {"text": "転職を考えているあなたへ", "start": 0.0, "end": 3.0}
                ],
            }
        ],
    }


def test_valid_screenplay_passes() -> None:
    screenplay_validator.validate_screenplay(_valid_screenplay())


def test_missing_caption_fails() -> None:
    sp = _valid_screenplay()
    del sp["caption"]
    with pytest.raises(ValueError) as exc:
        screenplay_validator.validate_screenplay(sp)
    assert "caption" in str(exc.value)


def test_empty_caption_fails() -> None:
    sp = _valid_screenplay()
    sp["caption"] = ""
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_empty_scenes_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"] = []
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_missing_duration_fails() -> None:
    sp = _valid_screenplay()
    del sp["scenes"][0]["duration"]
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_duration_below_minimum_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["duration"] = 2.5
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_missing_background_prompt_fails() -> None:
    sp = _valid_screenplay()
    del sp["scenes"][0]["background_prompt"]
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_line_text_forbidden_comma_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["text"] = "転職を,考える"
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_line_text_forbidden_period_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["text"] = "転職を考える."
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_full_width_punctuation_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["text"] = "転職を考えているあなたへ！"
    screenplay_validator.validate_screenplay(sp)


def test_line_start_beyond_duration_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["duration"] = 3.0
    sp["scenes"][0]["lines"][0]["start"] = 5.0
    with pytest.raises(ValueError) as exc:
        screenplay_validator.validate_screenplay(sp)
    assert "start" in str(exc.value)


def test_line_end_le_start_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0] = {"text": "x", "start": 2.0, "end": 1.5}
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_no_lines_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"] = []
    screenplay_validator.validate_screenplay(sp)


def test_title_overlay_allowed() -> None:
    sp = _valid_screenplay()
    sp["title_overlay"] = "未経験から\nITエンジニアに転職した末路"
    screenplay_validator.validate_screenplay(sp)


def test_audio_mode_silent_allowed() -> None:
    sp = _valid_screenplay()
    sp["audio_mode"] = "silent"
    screenplay_validator.validate_screenplay(sp)


def test_audio_mode_invalid_fails() -> None:
    sp = _valid_screenplay()
    sp["audio_mode"] = "mute"
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_scene_lipsync_boolean_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lipsync"] = False
    screenplay_validator.validate_screenplay(sp)


def test_strict_false_returns_errors() -> None:
    sp = _valid_screenplay()
    del sp["caption"]
    errors = screenplay_validator.validate_screenplay(sp, strict=False)
    assert len(errors) > 0


def test_line_emotion_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["emotion"] = "驚き"
    screenplay_validator.validate_screenplay(sp)


def test_line_delivery_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["delivery"] = "早口で語尾跳ね上がり"
    screenplay_validator.validate_screenplay(sp)


def test_line_acoustic_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["acoustic"] = {
        "pitch_hz_mean": 285,
        "pitch_trend": "rising",
        "rms_peak": 0.72,
        "wpm": 480,
    }
    screenplay_validator.validate_screenplay(sp)


def test_line_voice_overrides_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["voice_overrides"] = {
        "stability": 0.2, "style": 0.7,
    }
    screenplay_validator.validate_screenplay(sp)


def test_line_pronunciation_hints_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["pronunciation_hints"] = {"IT": "アイティー"}
    screenplay_validator.validate_screenplay(sp)


def test_pause_and_breath_fields_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["pause_before"] = 0.4
    sp["scenes"][0]["lines"][0]["breath_before"] = True
    screenplay_validator.validate_screenplay(sp)


def test_speaker_field_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["speaker"] = "主人公"
    screenplay_validator.validate_screenplay(sp)


def test_characters_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["characters"] = [
        {"name": "主人公", "role": "narrator", "ref": "female_engineer", "outfit": "グレーのリブニット"},
    ]
    screenplay_validator.validate_screenplay(sp)


def test_wardrobe_and_continuity_allowed() -> None:
    sp = _valid_screenplay()
    sp["wardrobe_continuity"] = {"office_outfit": "グレーのリブニット + ブラックパンツ"}
    sp["scenes"][0]["wardrobe"] = {
        "identifier": "office_outfit",
        "top": "リブニット",
        "bottom": "ブラックパンツ",
        "hair": "ロング",
    }
    screenplay_validator.validate_screenplay(sp)


def test_global_bgm_path_allowed() -> None:
    sp = _valid_screenplay()
    sp["bgm_path"] = "/abs/path/bgm.wav"
    sp["bgm_volume_db"] = -18
    screenplay_validator.validate_screenplay(sp)


def test_facial_expression_and_hand_gesture_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["facial_expression"] = "驚いて目を見開く"
    sp["scenes"][0]["hand_gesture"] = "頭を抱える"
    screenplay_validator.validate_screenplay(sp)
