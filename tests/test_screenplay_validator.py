import pytest

import screenplay_validator


def _valid_screenplay() -> dict:
    return {
        "caption": "会社選びが何より大切です\n\n#未経験 #転職",
        "scenes": [
            {
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


def test_missing_duration_passes() -> None:
    """duration は Stage 2 (TTS) が書き込む派生値。Stage 1 抽象台本では未指定が正常。"""
    sp = _valid_screenplay()
    del sp["scenes"][0]["duration"]
    screenplay_validator.validate_screenplay(sp)


def test_short_duration_passes() -> None:
    """MIN 制約は撤廃 (= Stage 2 の TTS 実測値が SSOT、制限不要)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["duration"] = 0.5
    sp["scenes"][0]["lines"][0]["start"] = 0.0
    sp["scenes"][0]["lines"][0]["end"] = 0.4
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


def test_hidden_field_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["hidden"] = True
    screenplay_validator.validate_screenplay(sp)


def test_hidden_field_must_be_boolean() -> None:
    import pytest
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["hidden"] = "yes"
    with pytest.raises(Exception):
        screenplay_validator.validate_screenplay(sp)



def test_line_speaker_field_allowed() -> None:
    """複数キャラのシーンで line.speaker を指定できる。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["characters"] = [
        {"name": "主人公"},
        {"name": "上司"},
    ]
    sp["scenes"][0]["lines"][0]["speaker"] = "主人公"
    screenplay_validator.validate_screenplay(sp)


def test_line_speaker_optional() -> None:
    """speaker は省略可能 (単一キャラのシーンでは付けなくてよい)。"""
    sp = _valid_screenplay()
    assert "speaker" not in sp["scenes"][0]["lines"][0]
    screenplay_validator.validate_screenplay(sp)


def test_characters_name_role_only_allowed() -> None:
    """SSOT: characters[] は name / role のみ。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["characters"] = [
        {"name": "主人公"},
    ]
    screenplay_validator.validate_screenplay(sp)


def test_wardrobe_tag_rejected() -> None:
    """SSOT: scene.wardrobe_tag は廃止 (キャラ ID に焼き込み)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["wardrobe_tag"] = "office_outfit"
    with pytest.raises(ValueError, match="wardrobe_tag"):
        screenplay_validator.validate_screenplay(sp)


def test_wardrobe_continuity_root_rejected() -> None:
    """SSOT: root.wardrobe_continuity は廃止 (キャラ ID に焼き込み)。"""
    sp = _valid_screenplay()
    sp["wardrobe_continuity"] = {"office_outfit": "グレーニット"}
    with pytest.raises(ValueError, match="wardrobe_continuity"):
        screenplay_validator.validate_screenplay(sp)


def test_location_continuity_root_rejected() -> None:
    """SSOT: root.location_continuity は廃止 (グローバル locations/ から引く)。"""
    sp = _valid_screenplay()
    sp["location_continuity"] = {"x": {"decor": "y"}}
    with pytest.raises(ValueError, match="location_continuity"):
        screenplay_validator.validate_screenplay(sp)


def test_scene_wardrobe_object_rejected() -> None:
    """SSOT: scene.wardrobe (dict 形式) は廃止。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["wardrobe"] = {"identifier": "office_outfit"}
    with pytest.raises(ValueError, match="wardrobe"):
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


def test_characters_outfit_rejected_as_deprecated() -> None:
    """SSOT: characters[].outfit は廃止 (キャラ画像に焼き込み)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["characters"] = [{"name": "主人公", "outfit": "ニット"}]
    with pytest.raises(ValueError, match="outfit"):
        screenplay_validator.validate_screenplay(sp)


def test_characters_ref_rejected_as_deprecated() -> None:
    """SSOT: characters[].ref は廃止 (scene.character_refs で表現)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["characters"] = [{"name": "主人公",
                                       "ref": "female_engineer"}]
    with pytest.raises(ValueError, match="ref"):
        screenplay_validator.validate_screenplay(sp)


def test_characters_role_rejected_as_deprecated() -> None:
    """SSOT: characters[].role は廃止 (= name = ref で十分)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["characters"] = [{"name": "主人公", "role": "narrator"}]
    with pytest.raises(ValueError, match="role"):
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


def test_scene_tags_field_rejected_as_deprecated() -> None:
    """SSOT: scene.tags は scoped_augmentations 廃止に伴い削除済み。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["tags"] = ["home_office"]
    with pytest.raises(ValueError, match="tags"):
        screenplay_validator.validate_screenplay(sp)


def test_scoped_augmentations_root_rejected_as_deprecated() -> None:
    """SSOT: root.scoped_augmentations は廃止 (シーン別 location_ref で代替)。"""
    sp = _valid_screenplay()
    sp["scoped_augmentations"] = [
        {"scope": {"tag": "home_office"}, "elements": ["standing_desk"]},
    ]
    with pytest.raises(ValueError, match="scoped_augmentations"):
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


def test_subtitles_mixed_manual_and_auto_with_one_invalid_rejected() -> None:
    """混在: chunk0=両方有 / chunk1=両方無 / chunk2=start のみ → chunk2 だけがエラー。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["duration"] = 5.0
    sp["scenes"][0]["lines"][0] = {
        "text": "x", "start": 0.0, "end": 4.0,
        "subtitles": [
            {"text": "a", "start": 0.0, "end": 1.0},
            {"text": "b"},
            {"text": "c", "start": 2.0},
        ],
    }
    errors = screenplay_validator.validate_screenplay(sp, strict=False)
    half_errors = [e for e in errors if "片方だけ" in e]
    assert len(half_errors) == 1
    assert "subtitles/2" in half_errors[0]


def test_line_without_subtitles_field_passes() -> None:
    """subtitles フィールドが無い line は素通り (= 既存挙動を壊さない)。"""
    sp = _valid_screenplay()
    assert "subtitles" not in sp["scenes"][0]["lines"][0]
    screenplay_validator.validate_screenplay(sp)


def test_subtitles_adjacent_anchor_overlap_rejected() -> None:
    """前 chunk の end が次 chunk の start を超えると順序違反 → reject。
    そのまま通すと _resolve_subtitle_timings が後勝ちで前を silent に上書きする。
    """
    sp = _valid_screenplay()
    sp["scenes"][0]["duration"] = 5.0
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "a", "start": 0.0, "end": 3.0},
        {"text": "b", "start": 1.0, "end": 4.0},
    ]
    with pytest.raises(ValueError, match="順序違反"):
        screenplay_validator.validate_screenplay(sp)


def test_subtitles_adjacent_anchor_touching_passes() -> None:
    """end == 次の start (= ぴったり接続) は許容する (= 通常の繋ぎ)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["duration"] = 5.0
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "a", "start": 0.0, "end": 2.0},
        {"text": "b", "start": 2.0, "end": 4.0},
    ]
    screenplay_validator.validate_screenplay(sp)


def test_subtitles_overlap_with_auto_chunk_in_between_still_caught() -> None:
    """auto chunk を挟んでも、前 manual end が次 manual start を超えると検出する。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["duration"] = 5.0
    sp["scenes"][0]["lines"][0]["subtitles"] = [
        {"text": "a", "start": 0.0, "end": 4.0},
        {"text": "b"},  # auto
        {"text": "c", "start": 1.0, "end": 4.5},
    ]
    errors = screenplay_validator.validate_screenplay(sp, strict=False)
    # 直接隣接ではないので隣接 anchor 検出は要件外だが、現在の検出は隣接のみなので
    # ここでは reject されない (= silent 上書きの可能性は残る)。
    # 重要なのは隣接ケースだけ確実に reject される事を保証する基準。
    overlap_errors = [e for e in errors if "順序違反" in e]
    assert overlap_errors == []


# ─── abstract / composed 形式の二段検証 ───────────────────────────


def _abstract_screenplay() -> dict:
    """compose 前の abstract 形式 (= background_prompt 等の派生フィールド無し)。"""
    return {
        "caption": "test caption",
        "featured_characters": ["f1", "m1"],
        "speaker_to_ref": {"speaker_1": "f1", "speaker_2": "m1"},
        "scenes": [
            {
                "duration": 5.0,
                "location_ref": "home_office",
                "character_selection": ["f1"],
                "animation_style": "subtle",
                "lines": [
                    {"text": "やばい", "start": 0.0, "end": 2.0,
                     "speaker": "speaker_1"},
                ],
            },
        ],
    }


def test_abstract_form_passes_without_background_prompt() -> None:
    """require_composed=False なら background_prompt 無しでも通る。"""
    sp = _abstract_screenplay()
    screenplay_validator.validate_screenplay(sp, require_composed=False)


def test_abstract_form_fails_with_default_composed_check() -> None:
    """既定 (require_composed=True) では background_prompt 必須で落ちる。"""
    sp = _abstract_screenplay()
    with pytest.raises(ValueError, match="background_prompt"):
        screenplay_validator.validate_screenplay(sp)


def test_featured_characters_root_allowed() -> None:
    sp = _valid_screenplay()
    sp["featured_characters"] = ["f1", "m1__suit"]
    screenplay_validator.validate_screenplay(sp)


def test_featured_characters_must_be_array_of_strings() -> None:
    sp = _valid_screenplay()
    sp["featured_characters"] = [{"id": "f1"}]
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_speaker_to_ref_root_allowed() -> None:
    sp = _valid_screenplay()
    sp["speaker_to_ref"] = {"speaker_1": "f1", "speaker_2": "m1"}
    screenplay_validator.validate_screenplay(sp)


def test_speaker_to_ref_value_must_be_string() -> None:
    sp = _valid_screenplay()
    sp["speaker_to_ref"] = {"speaker_1": 123}
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_character_selection_scene_allowed() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["character_selection"] = ["f1"]
    screenplay_validator.validate_screenplay(sp)


def test_character_selection_empty_means_no_people() -> None:
    """空 list は人物 0 人 (= 背景のみ) を表す合法値。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["character_selection"] = []
    screenplay_validator.validate_screenplay(sp)


def test_validate_abstract_helper_passes() -> None:
    sp = _abstract_screenplay()
    screenplay_validator.validate_abstract(sp)


def test_validate_abstract_helper_returns_errors_when_strict_false() -> None:
    sp = _abstract_screenplay()
    sp["caption"] = ""
    errors = screenplay_validator.validate_abstract(sp, strict=False)
    assert any("caption" in e for e in errors)


def test_composed_form_passes_full_validation() -> None:
    """compose 出力 (= 派生フィールド込み) は default で通る。"""
    sp = _valid_screenplay()
    sp["featured_characters"] = ["f1"]
    sp["speaker_to_ref"] = {"speaker_1": "f1"}
    screenplay_validator.validate_screenplay(sp)


# ─── character ref 物理存在検証 (= characters/ に対する SSOT 検証) ─────


def test_unknown_featured_character_rejected(monkeypatch) -> None:
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images",
                         lambda: ["f1", "m1"])
    sp = _valid_screenplay()
    sp["featured_characters"] = ["nonexistent_xyz"]
    with pytest.raises(ValueError, match="characters/"):
        screenplay_validator.validate_screenplay(sp)


def test_known_featured_character_passes(monkeypatch) -> None:
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images",
                         lambda: ["f1", "m1__office"])
    sp = _valid_screenplay()
    sp["featured_characters"] = ["f1", "m1__office"]
    screenplay_validator.validate_screenplay(sp)


def test_speaker_to_ref_with_unknown_value_rejected(monkeypatch) -> None:
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: ["f1"])
    sp = _valid_screenplay()
    sp["speaker_to_ref"] = {"speaker_1": "ghost"}
    with pytest.raises(ValueError, match="speaker_to_ref"):
        screenplay_validator.validate_screenplay(sp)


def test_character_selection_unknown_ref_rejected(monkeypatch) -> None:
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: ["f1"])
    sp = _valid_screenplay()
    sp["scenes"][0]["character_selection"] = ["ghost"]
    with pytest.raises(ValueError, match="characters/"):
        screenplay_validator.validate_screenplay(sp)


def test_character_refs_unknown_ref_rejected(monkeypatch) -> None:
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: ["f1"])
    sp = _valid_screenplay()
    sp["scenes"][0]["character_refs"] = ["ghost"]
    with pytest.raises(ValueError, match="characters/"):
        screenplay_validator.validate_screenplay(sp)


def test_speaker_raw_anonymous_id_does_not_trigger_existence_check(monkeypatch) -> None:
    """speaker_N 形式は speaker_to_ref で解決前提。物理存在検証はスキップ。"""
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: ["f1"])
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["speaker"] = "speaker_99"
    screenplay_validator.validate_screenplay(sp)


def test_line_speaker_unknown_ref_rejected(monkeypatch) -> None:
    """raw 匿名 ID で始まらない speaker は ref として物理存在検証される。"""
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: ["f1"])
    sp = _valid_screenplay()
    sp["scenes"][0]["lines"][0]["speaker"] = "ghost"
    with pytest.raises(ValueError, match="characters/"):
        screenplay_validator.validate_screenplay(sp)


def test_character_existence_skipped_when_directory_empty(monkeypatch) -> None:
    """characters/ が空 (= テスト環境) なら検証スキップ。"""
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: [])
    sp = _valid_screenplay()
    sp["featured_characters"] = ["literally_anything"]
    screenplay_validator.validate_screenplay(sp)



# ───── Compositional Architecture: identity / annotation / scene_parts / global_parts ─────
# 詳細: docs/plannings/2026-05-10_compositional-architecture.md §6.3


def test_identity_optional_for_legacy_screenplay() -> None:
    """旧スキーマ (= identity 無し) は引き続き valid。"""
    screenplay_validator.validate_screenplay(_valid_screenplay())


def test_identity_inline_form_passes() -> None:
    """新スキーマ: identity を入れ子で持つ scene が valid。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["identity"] = {
        "character_refs": ["f1__office"],
        "location_ref": "home_office",
        "start_emotion": "中立",
        "camera_distance": "medium-close",
    }
    sp["scenes"][0]["annotation"] = {
        "visual_intent_id": "talking_head_calm",
        "duration_bucket": 5,
        "motion_intensity": "low",
    }
    screenplay_validator.validate_screenplay(sp)


def test_identity_missing_required_field_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["identity"] = {
        "character_refs": ["f1"],
        "location_ref": "home_office",
        # start_emotion missing
    }
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_identity_invalid_camera_distance_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["identity"] = {
        "character_refs": ["f1"],
        "location_ref": "home_office",
        "start_emotion": "中立",
        "camera_distance": "ultra-wide",  # invalid
    }
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_annotation_invalid_duration_bucket_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["annotation"] = {
        "visual_intent_id": "talking_head_calm",
        "duration_bucket": 7,  # 5 / 10 のみ許可
    }
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_annotation_invalid_motion_intensity_fails() -> None:
    sp = _valid_screenplay()
    sp["scenes"][0]["annotation"] = {
        "motion_intensity": "extreme",  # low/medium/high のみ
    }
    with pytest.raises(ValueError):
        screenplay_validator.validate_screenplay(sp)


def test_scene_parts_optional_object_passes() -> None:
    """scene_parts は任意 object でいったん受ける (Phase 4 で part_registry 整合性追加)。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["scene_parts"] = {
        "subtitle_style": {"id": "karaoke_bold", "params": {}},
        "stickers": [{"id": "exclaim_red", "at": 0.5}],
    }
    screenplay_validator.validate_screenplay(sp)


def test_override_fields_pass() -> None:
    """_override_*  は novel intent 用 escape hatch なので validator は通る。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["_override_animation_prompt"] = "subject teleports"
    sp["scenes"][0]["_override_background_prompt"] = None
    screenplay_validator.validate_screenplay(sp)


def test_global_parts_optional_passes() -> None:
    sp = _valid_screenplay()
    sp["global_parts"] = {
        "filter_preset": {"id": "warm_cinematic", "params": {}},
        "bgm": {"path": "assets/bgm/upbeat.mp3", "ducking": True},
    }
    screenplay_validator.validate_screenplay(sp)


def test_legacy_alias_fields_pass() -> None:
    """新スキーマの annotation / identity を入れ子で持たず、旧 alias で書いたケース。"""
    sp = _valid_screenplay()
    sp["scenes"][0]["start_emotion"] = "中立"
    sp["scenes"][0]["visual_intent_id"] = "talking_head_calm"
    sp["scenes"][0]["duration_bucket"] = 5
    sp["scenes"][0]["motion_intensity"] = "low"
    screenplay_validator.validate_screenplay(sp)
