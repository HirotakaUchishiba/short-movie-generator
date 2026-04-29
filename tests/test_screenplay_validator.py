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


def test_characters_name_role_only_allowed() -> None:
    """SSOT: characters[] は name / role のみ。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["characters"] = [
        {"name": "主人公", "role": "narrator"},
    ]
    screenplay_validator.validate_screenplay(sp)


def test_wardrobe_identifier_only_allowed() -> None:
    """SSOT: wardrobe は identifier だけ。詳細は wardrobe_continuity に。"""
    sp = _valid_screenplay()
    sp["wardrobe_continuity"] = {"office_outfit": "グレーのリブニット + ブラックパンツ"}
    sp["scenes"][0]["wardrobe"] = {"identifier": "office_outfit"}
    screenplay_validator.validate_screenplay(sp)


def test_global_bgm_path_allowed() -> None:
    sp = _valid_screenplay()
    sp["bgm_path"] = "/abs/path/bgm.wav"
    sp["bgm_volume_db"] = -18
    screenplay_validator.validate_screenplay(sp)


def test_facial_expression_rejected_as_deprecated() -> None:
    """SSOT: scene.facial_expression は廃止 (lines[].emotion で表現)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["facial_expression"] = "驚いて目を見開く"
    with pytest.raises(ValueError, match="facial_expression"):
        screenplay_validator.validate_screenplay(sp)


def test_hand_gesture_rejected_as_deprecated() -> None:
    """SSOT: scene.hand_gesture は廃止 (lines[].emotion で表現)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["hand_gesture"] = "頭を抱える"
    with pytest.raises(ValueError, match="hand_gesture"):
        screenplay_validator.validate_screenplay(sp)


def test_wardrobe_top_rejected_as_deprecated() -> None:
    """SSOT: wardrobe.{top,bottom,accessories,hair} は廃止 (wardrobe_continuity で表現)。"""
    sp = _valid_screenplay()
    sp["scenes"][0].setdefault("wardrobe", {})["top"] = "ニット"
    with pytest.raises(ValueError, match="top"):
        screenplay_validator.validate_screenplay(sp)


def test_characters_outfit_rejected_as_deprecated() -> None:
    """SSOT: characters[].outfit は廃止 (wardrobe_continuity で表現)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["characters"] = [{"name": "主人公", "role": "narrator",
                                       "outfit": "ニット"}]
    with pytest.raises(ValueError, match="outfit"):
        screenplay_validator.validate_screenplay(sp)


def test_characters_ref_rejected_as_deprecated() -> None:
    """SSOT: characters[].ref は廃止 (scene.character_refs で表現)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["characters"] = [{"name": "主人公", "role": "narrator",
                                       "ref": "female_engineer"}]
    with pytest.raises(ValueError, match="ref"):
        screenplay_validator.validate_screenplay(sp)


def test_unknown_scene_field_rejected() -> None:
    """additionalProperties: False — 未知フィールドは reject。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["my_new_field"] = "anything"
    with pytest.raises(ValueError, match="my_new_field"):
        screenplay_validator.validate_screenplay(sp)


def test_unknown_root_field_rejected() -> None:
    sp = _valid_screenplay()
    sp["unknown_root"] = "x"
    with pytest.raises(ValueError, match="unknown_root"):
        screenplay_validator.validate_screenplay(sp)


def test_unknown_line_field_rejected() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["unknown_line_field"] = "x"
    with pytest.raises(ValueError, match="unknown_line_field"):
        screenplay_validator.validate_screenplay(sp)


def test_emotion_cue_overrides_with_preset_ids_allowed() -> None:
    """preset ID 経由の override は schema 通過。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["emotion_cue_overrides"] = {
        "facial": "alert_focused",
        "lighting": "warm_morning",
    }
    screenplay_validator.validate_screenplay(sp)


def test_emotion_cue_overrides_with_invalid_preset_rejected() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["emotion_cue_overrides"] = {"facial": "not_a_real_preset"}
    with pytest.raises(ValueError, match="not_a_real_preset"):
        screenplay_validator.validate_screenplay(sp)


def test_emotion_cue_overrides_unknown_category_rejected() -> None:
    """カテゴリも限定 (unknown_category 不可)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["emotion_cue_overrides"] = {"unknown_category": "neutral"}
    with pytest.raises(ValueError, match="unknown_category"):
        screenplay_validator.validate_screenplay(sp)


def test_scene_tags_with_known_tags_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["tags"] = ["home_office", "morning"]
    screenplay_validator.validate_screenplay(sp)


def test_scene_tags_with_unknown_tag_rejected() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["tags"] = ["unknown_tag"]
    with pytest.raises(ValueError, match="unknown_tag"):
        screenplay_validator.validate_screenplay(sp)


def test_scoped_augmentations_with_valid_data_allowed() -> None:
    sp = _valid_screenplay()
    sp["scoped_augmentations"] = [
        {
            "scope": {"tag": "home_office"},
            "elements": ["standing_desk", "plants_background"],
        },
    ]
    screenplay_validator.validate_screenplay(sp)


def test_scoped_augmentations_with_invalid_element_rejected() -> None:
    sp = _valid_screenplay()
    sp["scoped_augmentations"] = [
        {
            "scope": {"tag": "home_office"},
            "elements": ["fake_element"],
        },
    ]
    with pytest.raises(ValueError, match="fake_element"):
        screenplay_validator.validate_screenplay(sp)


def test_scoped_augmentations_missing_required_fields_rejected() -> None:
    sp = _valid_screenplay()
    sp["scoped_augmentations"] = [{"scope": {"tag": "home_office"}}]  # elements missing
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_subtitles_array_passes_validation() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "やばい", "start": 0.0, "end": 1.0},
        {"text": "セーフ", "start": 1.0, "end": 3.0},
    ]
    screenplay_validator.validate_screenplay(sp)


def test_subtitles_text_only_passes() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "やばい"},
        {"text": "セーフ"},
    ]
    screenplay_validator.validate_screenplay(sp)


def test_subtitles_only_start_rejected() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "やばい", "start": 0.0},
    ]
    with pytest.raises(ValueError, match="片方だけ"):
        screenplay_validator.validate_screenplay(sp)


def test_subtitles_only_end_rejected() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "やばい", "end": 1.0},
    ]
    with pytest.raises(ValueError, match="片方だけ"):
        screenplay_validator.validate_screenplay(sp)


def test_subtitles_missing_text_rejected() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"start": 0.0, "end": 1.0},
    ]
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_subtitles_unknown_property_rejected() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "x", "start": 0.0, "end": 1.0, "color": "#FFFFFF"},
    ]
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_subtitles_end_before_start_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "x", "start": 2.0, "end": 1.0},
    ]
    with pytest.raises(ValueError, match="end"):
        screenplay_validator.validate_screenplay(sp)


def test_subtitles_start_beyond_scene_duration_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["duration"] = 5.0
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "x", "start": 6.0, "end": 6.5},
    ]
    with pytest.raises(ValueError, match="シーン長"):
        screenplay_validator.validate_screenplay(sp)


def test_subtitles_empty_text_rejected() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "", "start": 0.0, "end": 1.0},
    ]
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)

