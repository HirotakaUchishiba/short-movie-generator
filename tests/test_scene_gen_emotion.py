import pytest

import scene_gen


def test_apply_pronunciation_hints_single() -> None:
    assert scene_gen._apply_pronunciation_hints("IT業界", {"IT": "アイティー"}) == "アイティー業界"


def test_apply_pronunciation_hints_multiple() -> None:
    assert scene_gen._apply_pronunciation_hints(
        "ITやPCの話", {"IT": "アイティー", "PC": "ピーシー"}
    ) == "アイティーやピーシーの話"


def test_apply_pronunciation_hints_none() -> None:
    assert scene_gen._apply_pronunciation_hints("そのまま", None) == "そのまま"


def test_apply_pronunciation_hints_global_dict_only() -> None:
    text = scene_gen._apply_pronunciation_hints(
        "ITとPC", None, global_dict={"IT": "アイティー", "PC": "ピーシー"},
    )
    assert text == "アイティーとピーシー"


def test_apply_pronunciation_hints_line_overrides_global() -> None:
    text = scene_gen._apply_pronunciation_hints(
        "IT業界",
        hints={"IT": "アイティー"},        # line override
        global_dict={"IT": "アイティー"},  # default reading
    )
    assert text == "アイティー業界"


def test_apply_pronunciation_hints_longer_keys_replace_first() -> None:
    text = scene_gen._apply_pronunciation_hints(
        "納期間に",
        hints=None,
        global_dict={"納期": "のうき", "納期間に": "のうきまに"},
    )
    assert text == "のうきまに"


def test_dominant_emotion_simple() -> None:
    scene = {"lines": [
        {"emotion": "驚き"},
        {"emotion": "喜び"},
        {"emotion": "驚き"},
    ]}
    assert scene_gen._dominant_emotion(scene) == "驚き"


def test_dominant_emotion_none_when_empty() -> None:
    assert scene_gen._dominant_emotion({"lines": []}) is None
    assert scene_gen._dominant_emotion({"lines": [{"text": "a"}]}) is None


def test_animation_prompt_appends_emotion_motion(monkeypatch) -> None:
    monkeypatch.setitem(
        scene_gen.config.EMOTION_MOTION_ADDONS, "驚き",
        "sudden startled motion",
    )
    scene = {
        "animation_prompt": "subject walks forward",
        "background_prompt": "office",
        "lines": [{"emotion": "驚き", "start": 0}],
    }
    result = scene_gen._get_animation_prompt(scene)
    assert "subject walks forward" in result
    assert "sudden startled motion" in result


def test_animation_prompt_no_emotion() -> None:
    scene = {
        "animation_prompt": "subject walks",
        "background_prompt": "office",
        "lines": [{"start": 0}],
    }
    assert scene_gen._get_animation_prompt(scene) == "subject walks"


def test_resolve_voice_settings_defaults() -> None:
    vs = scene_gen._resolve_voice_settings({"text": "x", "start": 0})
    assert vs["voice_id"] == scene_gen.config.ELEVENLABS_VOICE_ID
    assert vs["stability"] == scene_gen.config.ELEVENLABS_VOICE_STABILITY
    assert vs["speed"] == 1.0


def test_resolve_voice_settings_emotion_applies_preset(monkeypatch) -> None:
    monkeypatch.setitem(
        scene_gen.config.EMOTION_VOICE_PRESETS, "テスト感情",
        {"stability": 0.1, "style": 0.9, "similarity_boost": 0.9, "rate_pct": 25},
    )
    vs = scene_gen._resolve_voice_settings(
        {"text": "x", "start": 0, "emotion": "テスト感情"}
    )
    assert vs["stability"] == 0.1
    assert vs["style"] == 0.9
    assert vs["speed"] == pytest.approx(1.25)


def test_resolve_voice_settings_overrides_take_precedence(monkeypatch) -> None:
    monkeypatch.setitem(
        scene_gen.config.EMOTION_VOICE_PRESETS, "テスト感情",
        {"stability": 0.1, "style": 0.9, "similarity_boost": 0.9, "rate_pct": 25},
    )
    vs = scene_gen._resolve_voice_settings({
        "text": "x", "start": 0, "emotion": "テスト感情",
        "voice_overrides": {"stability": 0.7, "voice_id": "custom_voice"},
    })
    assert vs["stability"] == 0.7
    assert vs["voice_id"] == "custom_voice"
    assert vs["style"] == 0.9


def test_resolve_voice_settings_rate_overrides_emotion(monkeypatch) -> None:
    monkeypatch.setitem(
        scene_gen.config.EMOTION_VOICE_PRESETS, "テスト感情",
        {"stability": 0.5, "style": 0.5, "similarity_boost": 0.75, "rate_pct": 20},
    )
    vs = scene_gen._resolve_voice_settings({
        "text": "x", "start": 0, "emotion": "テスト感情", "rate": "-10%",
    })
    assert vs["speed"] == pytest.approx(0.9)


def test_wpm_to_rate_pct_baseline() -> None:
    assert scene_gen._wpm_to_rate_pct(scene_gen.config.WPM_BASELINE) == 0


def test_wpm_to_rate_pct_fast() -> None:
    rate = scene_gen._wpm_to_rate_pct(450)
    assert 5 <= rate <= scene_gen.config.WPM_RATE_BOUND_PCT


def test_wpm_to_rate_pct_slow() -> None:
    rate = scene_gen._wpm_to_rate_pct(150)
    assert -scene_gen.config.WPM_RATE_BOUND_PCT <= rate <= -5


def test_resolve_voice_settings_uses_wpm_when_no_explicit_rate() -> None:
    vs = scene_gen._resolve_voice_settings({
        "text": "x", "start": 0,
        "acoustic": {"wpm": 450},
    })
    assert vs["rate_pct"] != 0


def test_resolve_voice_settings_pitch_trend_adjusts_style(monkeypatch) -> None:
    base_style = scene_gen.config.ELEVENLABS_VOICE_STYLE
    vs = scene_gen._resolve_voice_settings({
        "text": "x", "start": 0,
        "acoustic": {"pitch_trend": "rising"},
    })
    assert vs["style"] > base_style


def test_build_tts_text_appends_delivery_tag(monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "DELIVERY_TAG_ENABLED", True)
    text = scene_gen._build_tts_text({
        "text": "セーフ", "delivery": "嬉しそうに弾んだ声で", "start": 0,
    })
    assert "嬉しそうに弾んだ声で" in text
    assert "セーフ" in text
    assert text.startswith("[")


def test_build_tts_text_no_delivery_returns_clean_only(monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "DELIVERY_TAG_ENABLED", True)
    text = scene_gen._build_tts_text({"text": "セーフ", "start": 0})
    assert text == "セーフ"


def test_build_tts_text_disabled_skips_tag(monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "DELIVERY_TAG_ENABLED", False)
    text = scene_gen._build_tts_text({
        "text": "セーフ", "delivery": "明るく", "start": 0,
    })
    assert "[" not in text


def test_rms_to_volume_db_quiet() -> None:
    db = scene_gen._rms_to_volume_db(0.15)
    assert db == scene_gen.config.RMS_VOLUME_QUIET_DB


def test_rms_to_volume_db_loud() -> None:
    db = scene_gen._rms_to_volume_db(0.7)
    assert db == scene_gen.config.RMS_VOLUME_LOUD_DB


def test_rms_to_volume_db_normal_returns_none() -> None:
    assert scene_gen._rms_to_volume_db(0.4) is None
    assert scene_gen._rms_to_volume_db(None) is None


def test_build_background_prompt_includes_wardrobe_and_expression() -> None:
    sp = {
        "wardrobe_continuity": {"office": "グレーニット + ブラックパンツ"},
    }
    scene = {
        "background_prompt": "オフィス背景",
        "wardrobe": {"identifier": "office", "hair": "ロング"},
        "facial_expression": "微笑む",
        "hand_gesture": "PCを指差す",
    }
    prompt = scene_gen._build_background_prompt(scene, sp)
    assert "オフィス背景" in prompt
    assert "グレーニット" in prompt
    assert "ロング" in prompt
    assert "微笑む" in prompt
    assert "PCを指差す" in prompt


def test_build_background_prompt_multi_character() -> None:
    scene = {
        "background_prompt": "会議室",
        "characters": [
            {"name": "主人公", "role": "narrator", "outfit": "グレー"},
            {"name": "上司", "role": "boss", "outfit": "ジャケット"},
        ],
    }
    prompt = scene_gen._build_background_prompt(scene)
    assert "主人公" in prompt
    assert "上司" in prompt
    assert "boss" in prompt


def test_neighbor_line_text_within_scene() -> None:
    sp = {"scenes": [{"lines": [{"text": "A"}, {"text": "B"}, {"text": "C"}]}]}
    assert scene_gen._neighbor_line_text(sp, 0, 1, "prev") == "A"
    assert scene_gen._neighbor_line_text(sp, 0, 1, "next") == "C"


def test_neighbor_line_text_crosses_scene_boundary() -> None:
    sp = {
        "scenes": [
            {"lines": [{"text": "A"}, {"text": "B"}]},
            {"lines": [{"text": "C"}, {"text": "D"}]},
        ]
    }
    assert scene_gen._neighbor_line_text(sp, 1, 0, "prev") == "B"
    assert scene_gen._neighbor_line_text(sp, 0, 1, "next") == "C"


def test_neighbor_line_text_skips_empty_scenes() -> None:
    sp = {
        "scenes": [
            {"lines": [{"text": "A"}]},
            {"lines": []},
            {"lines": [{"text": "C"}]},
        ]
    }
    assert scene_gen._neighbor_line_text(sp, 2, 0, "prev") == "A"
    assert scene_gen._neighbor_line_text(sp, 0, 0, "next") == "C"


def test_neighbor_line_text_returns_none_at_extremes() -> None:
    sp = {"scenes": [{"lines": [{"text": "A"}]}]}
    assert scene_gen._neighbor_line_text(sp, 0, 0, "prev") is None
    assert scene_gen._neighbor_line_text(sp, 0, 0, "next") is None


def test_neighbor_line_text_handles_none_screenplay() -> None:
    assert scene_gen._neighbor_line_text(None, 0, 0, "prev") is None
    assert scene_gen._neighbor_line_text(None, 0, 0, "next") is None


def test_build_tts_text_uses_tts_text_override(monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "DELIVERY_TAG_ENABLED", True)
    text = scene_gen._build_tts_text({
        "text": "弊社都合で受け入れテストを",  # 字幕用
        "tts_text": "ヘイシャツゴーでうけいれテストを",  # TTS用上書き
        "delivery": "淡々と",
        "pronunciation_hints": {"弊社都合": "別の何か"},  # 上書き時は無視されるべき
        "start": 0,
    })
    assert "ヘイシャツゴーでうけいれテストを" in text
    assert "別の何か" not in text
    assert text.startswith("[淡々と]")


def test_build_tts_text_empty_tts_text_falls_back_to_normal(monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "DELIVERY_TAG_ENABLED", False)
    text = scene_gen._build_tts_text({
        "text": "セーフ",
        "tts_text": "",  # 空文字 = 上書きしない
        "start": 0,
    })
    assert text == "セーフ"


def test_clean_text_normalizes_uncommon_punctuation() -> None:
    assert scene_gen._clean_text("え年収200万アップ⁉") == "え年収200万アップ!?"
    assert scene_gen._clean_text("最高‼") == "最高!!"
    assert scene_gen._clean_text("便利〜") == "便利ー"
    assert scene_gen._clean_text("…そうか") == "そうか"
