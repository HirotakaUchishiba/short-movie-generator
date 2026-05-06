"""グローバル locations/<id>.json 経由での背景一貫性検証。

scene.location_ref → analyze.location.load_location(<id>) で詳細を引き当て、
scene_gen._build_background_prompt に注入される。
"""

import pytest

import scene_gen
from analyze import location as loc_mod
from screenplay_validator import validate_screenplay


@pytest.fixture
def isolated_locations(tmp_path, monkeypatch):
    monkeypatch.setattr(loc_mod, "LOCATIONS_DIR", tmp_path / "locations")
    return loc_mod


def _scene(**kw) -> dict:
    base = {
        "duration": 5.0,
        "background_prompt": "デスクに向かう女性",
        "lines": [],
    }
    base.update(kw)
    return base


def _sp(scenes) -> dict:
    return {"caption": "test", "scenes": scenes}


def test_build_bg_prompt_injects_location_at_head(isolated_locations) -> None:
    """location_ref → locations/<id>.json の各属性が prompt 先頭に注入される
    (camera_distance 除く = compose 側で文に組み込まれる)。"""
    isolated_locations.save_location(isolated_locations.Location(
        id="home_office",
        decor="ナチュラルウッドのデスク",
        lighting="柔らかい自然光",
        color_palette="白基調",
        props="MacBook と白マグ",
        camera_distance="medium-close",
    ))
    sp = _sp([_scene(location_ref="home_office")])
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)

    decor_pos = out.index("ナチュラルウッド")
    bg_pos = out.index("デスクに向かう女性")
    assert decor_pos < bg_pos

    assert "location decor" in out
    assert "location lighting" in out
    assert "location color palette" in out
    assert "location props" in out


def test_build_bg_prompt_no_ref_skips_location(isolated_locations) -> None:
    isolated_locations.save_location(isolated_locations.Location(
        id="home_office", decor="X",
    ))
    sp = _sp([_scene()])
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "location decor" not in out


def test_build_bg_prompt_partial_location_fields(isolated_locations) -> None:
    """ロケ属性は任意。指定された属性だけ注入される。"""
    isolated_locations.save_location(isolated_locations.Location(
        id="bedroom", decor="ベッドのある部屋",
    ))
    sp = _sp([_scene(location_ref="bedroom")])
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "location decor" in out
    assert "ベッドのある部屋" in out
    assert "location lighting" not in out
    assert "location props" not in out


def test_location_lighting_suppresses_emotion_lighting_cue(isolated_locations) -> None:
    """ロケ側で lighting を指定したら emotion 由来の lighting cue は出さない。"""
    isolated_locations.save_location(isolated_locations.Location(
        id="loc1", lighting="朝の自然光",
    ))
    sp = _sp([_scene(
        location_ref="loc1",
        lines=[{"text": "x", "start": 0, "emotion": "驚き"}],
    )])
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "location lighting: 朝の自然光" in out
    assert "lighting and color:" not in out


def test_location_color_palette_also_suppresses_emotion_lighting(
    isolated_locations,
) -> None:
    isolated_locations.save_location(isolated_locations.Location(
        id="loc1", color_palette="白基調",
    ))
    sp = _sp([_scene(
        location_ref="loc1",
        lines=[{"text": "x", "start": 0, "emotion": "驚き"}],
    )])
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "lighting and color:" not in out


def test_emotion_lighting_kept_when_no_location_lighting(
    isolated_locations,
) -> None:
    """ロケが lighting も color_palette も指定しない場合は emotion 由来を出す。"""
    isolated_locations.save_location(isolated_locations.Location(
        id="loc1", decor="X",
    ))
    sp = _sp([_scene(
        location_ref="loc1",
        lines=[{"text": "x", "start": 0, "emotion": "驚き"}],
    )])
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "lighting and color:" in out


def test_build_bg_prompt_no_location_loaded(isolated_locations) -> None:
    """ref が locations/ に無くてもクラッシュしない。"""
    sp = _sp([_scene(location_ref="missing_loc")])
    out = scene_gen._build_background_prompt(sp["scenes"][0], sp)
    assert "デスクに向かう女性" in out
    assert "location decor" not in out


# ───────────────────────── validator ─────────────────────────


def test_validator_accepts_known_location_ref(isolated_locations) -> None:
    isolated_locations.save_location(isolated_locations.Location(
        id="home_office", decor="X", lighting="Y",
    ))
    sp = _sp([_scene(location_ref="home_office")])
    errors = validate_screenplay(sp, strict=False)
    assert errors == []


def test_validator_rejects_unknown_location_ref(isolated_locations) -> None:
    isolated_locations.save_location(isolated_locations.Location(
        id="home_office", decor="X",
    ))
    sp = _sp([_scene(location_ref="missing_loc")])
    errors = validate_screenplay(sp, strict=False)
    assert any("missing_loc" in e and "未定義" in e for e in errors)


def test_validator_allows_no_location_ref(isolated_locations) -> None:
    sp = _sp([_scene()])
    errors = validate_screenplay(sp, strict=False)
    assert errors == []
