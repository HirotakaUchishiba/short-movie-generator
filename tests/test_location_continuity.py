"""動画内で背景・小道具・ライティングを一貫させる location_continuity の検証。"""

import pytest

import scene_gen
from screenplay_validator import validate_screenplay


def _scene(**kw) -> dict:
    base = {
        "duration": 5.0,
        "background_prompt": "デスクに向かう女性",
        "lines": [],
    }
    base.update(kw)
    return base


def _sp(scenes, **root) -> dict:
    base = {"caption": "test", "scenes": scenes}
    base.update(root)
    return base


# ───────────────────────── composer ─────────────────────────


def test_build_bg_prompt_injects_location_at_head() -> None:
    """location_ref → location_continuity[ref] の各属性が prompt 先頭に注入される。"""
    sp = _sp(
        [_scene(location_ref="home_office")],
        location_continuity={
            "home_office": {
                "decor": "ナチュラルウッドのデスク",
                "lighting": "柔らかい自然光",
                "color_palette": "白基調",
                "props": "MacBook と白マグ",
                "camera_distance": "medium-close",
            }
        },
    )
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)

    # シーン固有 prompt より前にロケ要素が並ぶ
    decor_pos = out.index("ナチュラルウッド")
    bg_pos = out.index("デスクに向かう女性")
    assert decor_pos < bg_pos

    assert "location decor" in out
    assert "location lighting" in out
    assert "location color palette" in out
    assert "location props" in out
    assert "location camera distance" in out


def test_build_bg_prompt_no_ref_skips_location() -> None:
    """location_ref が無いシーンはロケ注入されない。"""
    sp = _sp(
        [_scene()],
        location_continuity={"home_office": {"decor": "X"}},
    )
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "location decor" not in out


def test_build_bg_prompt_partial_location_fields() -> None:
    """ロケ属性は任意。指定された属性だけ注入される。"""
    sp = _sp(
        [_scene(location_ref="bedroom")],
        location_continuity={"bedroom": {"decor": "ベッドのある部屋"}},
    )
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "location decor" in out
    assert "ベッドのある部屋" in out
    assert "location lighting" not in out
    assert "location props" not in out


def test_location_lighting_suppresses_emotion_lighting_cue() -> None:
    """ロケ側で lighting を指定したら emotion 由来の lighting cue は出さない
    (動画スコープのロケ整合性を優先)。"""
    sp = _sp(
        [_scene(location_ref="loc1",
                lines=[{"text": "x", "start": 0, "emotion": "驚き"}])],
        location_continuity={
            "loc1": {"lighting": "朝の自然光"},
        },
    )
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "location lighting: 朝の自然光" in out
    # emotion 由来 (例: subtle key light bump) は抑止される
    assert "lighting and color:" not in out


def test_location_color_palette_also_suppresses_emotion_lighting() -> None:
    """color_palette 指定でも emotion lighting は抑止される (整合性のため)。"""
    sp = _sp(
        [_scene(location_ref="loc1",
                lines=[{"text": "x", "start": 0, "emotion": "驚き"}])],
        location_continuity={
            "loc1": {"color_palette": "白基調"},
        },
    )
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "lighting and color:" not in out


def test_emotion_lighting_kept_when_no_location_lighting() -> None:
    """ロケが lighting も color_palette も指定しない場合は emotion 由来を出す。"""
    sp = _sp(
        [_scene(location_ref="loc1",
                lines=[{"text": "x", "start": 0, "emotion": "驚き"}])],
        location_continuity={
            "loc1": {"decor": "X"},
        },
    )
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "lighting and color:" in out


def test_build_bg_prompt_no_location_continuity_root() -> None:
    """root に location_continuity が無くてもクラッシュしない。"""
    sp = _sp([_scene(location_ref="home_office")])
    # ref が無効でも composer は素通り (validator 側で別途エラー)
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "デスクに向かう女性" in out
    assert "location decor" not in out


# ───────────────────────── validator ─────────────────────────


def test_validator_accepts_location_continuity() -> None:
    sp = _sp(
        [_scene(location_ref="home_office")],
        location_continuity={
            "home_office": {
                "decor": "X",
                "lighting": "Y",
            }
        },
    )
    errors = validate_screenplay(sp, strict=False)
    assert errors == []


def test_validator_rejects_unknown_location_ref() -> None:
    sp = _sp(
        [_scene(location_ref="missing_loc")],
        location_continuity={
            "home_office": {"decor": "X"},
        },
    )
    errors = validate_screenplay(sp, strict=False)
    assert any("missing_loc" in e and "未定義" in e for e in errors)


def test_validator_rejects_unknown_location_attribute() -> None:
    """location_continuity の属性は固定 5 種以外を拒否 (誤字防止)。"""
    sp = _sp(
        [_scene(location_ref="home_office")],
        location_continuity={
            "home_office": {"foo_bar": "誤った属性"},
        },
    )
    errors = validate_screenplay(sp, strict=False)
    assert any("foo_bar" in e or "additional" in e.lower() for e in errors)


def test_validator_allows_no_location_ref() -> None:
    """location_ref は任意。何も書かない既存台本は引き続き通る。"""
    sp = _sp([_scene()])
    errors = validate_screenplay(sp, strict=False)
    assert errors == []


def test_validator_allows_partial_location_attributes() -> None:
    """location_continuity の各属性は任意 (decor だけ等もOK)。"""
    sp = _sp(
        [_scene(location_ref="home_office")],
        location_continuity={"home_office": {"decor": "X only"}},
    )
    errors = validate_screenplay(sp, strict=False)
    assert errors == []
