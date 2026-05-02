"""analyze.style の単体テスト (VideoStyle データモデル + CRUD)。"""
import pytest


@pytest.fixture
def isolated_styles(tmp_path, monkeypatch):
    from analyze import style as _style
    monkeypatch.setattr(_style, "STYLES_DIR", tmp_path / "styles")
    return _style


def _minimum_dict(name: str = "test_style") -> dict:
    return {
        "name": name,
        "characters": [
            {"name": "主人公", "role": "narrator", "ref": "female_engineer"},
        ],
    }


def _full_dict(name: str = "full") -> dict:
    return {
        "name": name,
        "format": "narrator",
        "characters": [
            {"name": "主人公", "role": "narrator", "ref": "female_engineer",
             "voice_overrides": {"stability": 0.4, "style": 0.3}},
        ],
        "wardrobe_continuity": {"office": "グレーニット"},
        "default_wardrobe": "office",
        "location_continuity": {
            "home_office": {
                "decor": "ミニマル", "lighting": "自然光",
                "color_palette": "白", "props": "MacBook",
                "camera_distance": "medium",
            },
        },
        "default_location": "home_office",
        "default_tags": ["home_office"],
        "scoped_augmentations": [],
        "animation_style": "subtle",
    }


def test_save_and_load_round_trip(isolated_styles):
    style = isolated_styles.VideoStyle.from_dict(_full_dict())
    isolated_styles.save_style(style)
    loaded = isolated_styles.load_style("full")
    assert loaded.to_dict() == _full_dict()


def test_load_missing_raises(isolated_styles):
    with pytest.raises(FileNotFoundError):
        isolated_styles.load_style("nope")


def test_validate_requires_at_least_one_character(isolated_styles):
    style = isolated_styles.VideoStyle.from_dict(
        {"name": "x", "characters": []},
    )
    errors = style.validate()
    assert any("characters" in e for e in errors)


def test_validate_default_wardrobe_must_be_in_continuity(isolated_styles):
    d = _minimum_dict()
    d["default_wardrobe"] = "nonexistent"
    style = isolated_styles.VideoStyle.from_dict(d)
    errors = style.validate()
    assert any("default_wardrobe" in e for e in errors)


def test_validate_default_location_must_be_in_continuity(isolated_styles):
    d = _minimum_dict()
    d["default_location"] = "nonexistent"
    style = isolated_styles.VideoStyle.from_dict(d)
    errors = style.validate()
    assert any("default_location" in e for e in errors)


def test_validate_invalid_camera_distance(isolated_styles):
    d = _minimum_dict()
    d["location_continuity"] = {
        "x": {"decor": "", "lighting": "", "color_palette": "",
              "props": "", "camera_distance": "extra-close"},
    }
    style = isolated_styles.VideoStyle.from_dict(d)
    errors = style.validate()
    assert any("camera_distance" in e for e in errors)


def test_validate_invalid_format(isolated_styles):
    d = _minimum_dict()
    d["format"] = "monologue"  # 不正
    style = isolated_styles.VideoStyle.from_dict(d)
    errors = style.validate()
    assert any("format" in e for e in errors)


def test_validate_invalid_animation_style(isolated_styles):
    d = _minimum_dict()
    d["animation_style"] = "wild"
    style = isolated_styles.VideoStyle.from_dict(d)
    errors = style.validate()
    assert any("animation_style" in e for e in errors)


def test_validate_duplicate_character_name(isolated_styles):
    d = _minimum_dict()
    d["characters"] = [
        {"name": "主人公", "role": "narrator", "ref": "female_engineer"},
        {"name": "主人公", "role": "boss", "ref": "male_engineer"},
    ]
    style = isolated_styles.VideoStyle.from_dict(d)
    errors = style.validate()
    assert any("duplicate" in e for e in errors)


def test_save_invalid_raises(isolated_styles):
    bad = isolated_styles.VideoStyle.from_dict({"name": "x", "characters": []})
    with pytest.raises(ValueError):
        isolated_styles.save_style(bad)


def test_invalid_name_path_traversal_blocked(isolated_styles):
    with pytest.raises(ValueError):
        isolated_styles._path("../etc/passwd")
    with pytest.raises(ValueError):
        isolated_styles._path("a/b")


def test_list_styles_alphabetical(isolated_styles):
    isolated_styles.save_style(
        isolated_styles.VideoStyle.from_dict(_minimum_dict("zeta")),
    )
    isolated_styles.save_style(
        isolated_styles.VideoStyle.from_dict(_minimum_dict("alpha")),
    )
    assert isolated_styles.list_styles() == ["alpha", "zeta"]


def test_delete_style_returns_false_when_missing(isolated_styles):
    isolated_styles.save_style(
        isolated_styles.VideoStyle.from_dict(_minimum_dict("a")),
    )
    assert isolated_styles.delete_style("a") is True
    assert isolated_styles.delete_style("a") is False


def test_default_styles_load_and_validate():
    """同梱された 5 個のデフォルトテンプレが全部 valid であることを確認。"""
    from analyze import style as _style
    expected = {"office_engineer", "cafe_barista", "living_room_lifestyle",
                "simple_background", "outdoor_park"}
    available = set(_style.list_styles())
    assert expected.issubset(available), f"missing defaults: {expected - available}"
    for name in expected:
        s = _style.load_style(name)
        errors = s.validate()
        assert not errors, f"{name} has validation errors: {errors}"
