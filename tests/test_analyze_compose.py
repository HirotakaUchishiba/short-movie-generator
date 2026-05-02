"""analyze.compose の単体テスト (抽象台本 + VideoStyle → 完全 screenplay)。"""
import pytest

from analyze.compose import compose_screenplay
from analyze.style import CharacterDef, LocationDef, VideoStyle


def _abstract_minimal() -> dict:
    return {
        "caption": "test caption",
        "scenes": [
            {
                "duration": 5.0,
                "lines": [
                    {"text": "やばい", "start": 0, "end": 2,
                     "emotion": "焦り", "delivery": "早口"},
                    {"text": "セーフ", "start": 2.5, "end": 4,
                     "emotion": "安堵", "delivery": "ほっと"},
                ],
            },
        ],
    }


def _style_default() -> VideoStyle:
    return VideoStyle(
        name="x",
        characters=[
            CharacterDef(
                name="主人公", role="narrator", ref="female_engineer",
                voice_overrides={"stability": 0.4},
            ),
        ],
        wardrobe_continuity={"office": "グレーニット"},
        default_wardrobe="office",
        location_continuity={
            "home_office": LocationDef(
                decor="北欧風オフィス", lighting="自然光",
                color_palette="白基調", props="MacBook",
                camera_distance="medium-close",
            ),
        },
        default_location="home_office",
        default_tags=["home_office"],
        animation_style="standard",
    )


def test_compose_basic_round_trip():
    sp = compose_screenplay(_abstract_minimal(), _style_default())
    assert sp["caption"] == "test caption"
    assert "office" in sp["wardrobe_continuity"]
    assert "home_office" in sp["location_continuity"]
    assert len(sp["scenes"]) == 1
    scene = sp["scenes"][0]
    assert scene["duration"] == 5.0
    assert scene["wardrobe"]["identifier"] == "office"
    assert scene["location_ref"] == "home_office"
    assert scene["tags"] == ["home_office"]
    assert scene["lipsync"] is True
    assert "medium close-up shot" in scene["background_prompt"]
    assert "主人公" in scene["background_prompt"]
    assert "グレーニット" in scene["background_prompt"]
    assert "北欧風" in scene["background_prompt"]


def test_compose_animation_includes_emotion_arc_and_style():
    sp = compose_screenplay(_abstract_minimal(), _style_default())
    anim = sp["scenes"][0]["animation_prompt"]
    assert "焦り" in anim
    assert "安堵" in anim
    assert "natural hand gestures" in anim  # standard style


def test_compose_animation_expressive_style():
    style = _style_default()
    style.animation_style = "expressive"
    sp = compose_screenplay(_abstract_minimal(), style)
    assert "energetic" in sp["scenes"][0]["animation_prompt"]


def test_compose_animation_subtle_style():
    style = _style_default()
    style.animation_style = "subtle"
    sp = compose_screenplay(_abstract_minimal(), style)
    assert "minimal hand movement" in sp["scenes"][0]["animation_prompt"]


def test_compose_voice_overrides_injected_for_single_char():
    """単一キャラ動画では speaker 省略でもデフォルト voice が注入される。"""
    sp = compose_screenplay(_abstract_minimal(), _style_default())
    line0 = sp["scenes"][0]["lines"][0]
    assert "voice_overrides" in line0
    assert line0["voice_overrides"]["stability"] == 0.4


def test_compose_scene_overrides():
    abstract = _abstract_minimal()
    style = _style_default()
    style.wardrobe_continuity["weekend"] = "パーカー"
    style.location_continuity["park"] = LocationDef(
        decor="公園", camera_distance="wide",
    )
    sp = compose_screenplay(abstract, style, overrides={
        0: {"wardrobe": "weekend", "location_ref": "park",
            "tags": ["outdoor"]},  # outdoor は SCENE_TAGS にある
    })
    scene = sp["scenes"][0]
    assert scene["wardrobe"]["identifier"] == "weekend"
    assert scene["location_ref"] == "park"
    assert scene["tags"] == ["outdoor"]
    assert "wide shot" in scene["background_prompt"]


def test_compose_dialogue_subsets_to_speaking_characters():
    abstract = {
        "caption": "x",
        "scenes": [{
            "duration": 5,
            "lines": [
                {"text": "a", "start": 0, "end": 1, "speaker": "上司"},
                {"text": "b", "start": 1, "end": 2, "speaker": "上司"},
            ],
        }],
    }
    style = VideoStyle(
        name="x", format="dialogue",
        characters=[
            CharacterDef(name="主人公", role="narrator", ref="female_engineer"),
            CharacterDef(name="上司", role="boss", ref="male_engineer"),
        ],
        wardrobe_continuity={"a": "x"}, default_wardrobe="a",
        location_continuity={"b": LocationDef(camera_distance="medium")},
        default_location="b",
    )
    sp = compose_screenplay(abstract, style)
    names = {c["name"] for c in sp["scenes"][0]["characters"]}
    assert names == {"上司"}


def test_compose_dialogue_voice_resolution_per_speaker():
    abstract = {
        "caption": "", "scenes": [{
            "duration": 5,
            "lines": [
                {"text": "a", "start": 0, "end": 1, "speaker": "主人公"},
                {"text": "b", "start": 1, "end": 2, "speaker": "上司"},
            ],
        }],
    }
    style = VideoStyle(
        name="x", format="dialogue",
        characters=[
            CharacterDef(name="主人公", role="narrator", ref="female_engineer",
                          voice_overrides={"voice_id": "voice_p"}),
            CharacterDef(name="上司", role="boss", ref="male_engineer",
                          voice_overrides={"voice_id": "voice_b"}),
        ],
        wardrobe_continuity={"x": "x"}, default_wardrobe="x",
        location_continuity={"x": LocationDef(camera_distance="medium")},
        default_location="x",
    )
    sp = compose_screenplay(abstract, style)
    lines = sp["scenes"][0]["lines"]
    assert lines[0]["voice_overrides"]["voice_id"] == "voice_p"
    assert lines[1]["voice_overrides"]["voice_id"] == "voice_b"


def test_compose_passes_strict_validator():
    """合成結果が screenplay_validator strict を通る。"""
    from screenplay_validator import validate_screenplay
    sp = compose_screenplay(_abstract_minimal(), _style_default())
    validate_screenplay(sp, strict=True)


def test_compose_with_default_style_files_passes_validator():
    """同梱された 5 個のデフォルトテンプレで合成して strict validator を通る。"""
    from analyze import style as _style
    from screenplay_validator import validate_screenplay
    abstract = _abstract_minimal()
    for name in _style.list_styles():
        s = _style.load_style(name)
        sp = compose_screenplay(abstract, s)
        validate_screenplay(sp, strict=True)
