"""analyze.location の単体テスト (Location dataclass + CRUD)。"""
import pytest


@pytest.fixture
def isolated_locations(tmp_path, monkeypatch):
    from analyze import location as loc_mod
    monkeypatch.setattr(loc_mod, "LOCATIONS_DIR", tmp_path / "locations")
    return loc_mod


def test_save_and_load_round_trip(isolated_locations):
    loc = isolated_locations.Location(
        id="home_office",
        decor="北欧風",
        lighting="自然光",
        color_palette="白基調",
        props="MacBook",
        camera_distance="medium-close",
    )
    isolated_locations.save_location(loc)
    loaded = isolated_locations.load_location("home_office")
    assert loaded.id == "home_office"
    assert loaded.decor == "北欧風"
    assert loaded.camera_distance == "medium-close"


def test_load_missing_raises(isolated_locations):
    with pytest.raises(FileNotFoundError):
        isolated_locations.load_location("nope")


def test_validate_invalid_camera_distance(isolated_locations):
    loc = isolated_locations.Location(id="x", camera_distance="extra-close")
    errors = loc.validate()
    assert any("camera_distance" in e for e in errors)


def test_validate_requires_id(isolated_locations):
    loc = isolated_locations.Location(id="")
    errors = loc.validate()
    assert any("id" in e for e in errors)


def test_save_invalid_raises(isolated_locations):
    bad = isolated_locations.Location(id="x", camera_distance="bad")
    with pytest.raises(ValueError):
        isolated_locations.save_location(bad)


def test_invalid_id_path_traversal_blocked(isolated_locations):
    with pytest.raises(ValueError):
        isolated_locations._path("../etc/passwd")


def test_list_locations_alphabetical(isolated_locations):
    isolated_locations.save_location(isolated_locations.Location(id="zeta"))
    isolated_locations.save_location(isolated_locations.Location(id="alpha"))
    assert isolated_locations.list_locations() == ["alpha", "zeta"]


def test_delete_location(isolated_locations):
    isolated_locations.save_location(isolated_locations.Location(id="a"))
    assert isolated_locations.delete_location("a") is True
    assert isolated_locations.delete_location("a") is False


def test_load_fills_id_when_missing(isolated_locations, tmp_path):
    """JSON に id が無くてもファイル名から補完される。"""
    import json
    p = tmp_path / "locations" / "abc.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump({"decor": "X"}, f)
    loc = isolated_locations.load_location("abc")
    assert loc.id == "abc"
    assert loc.decor == "X"


def test_build_location_catalog_returns_full_dicts(isolated_locations):
    """build_location_catalog は全ロケを id + 属性付き dict list で返す。"""
    isolated_locations.save_location(isolated_locations.Location(
        id="home_office", decor="北欧風", camera_distance="medium-close",
    ))
    isolated_locations.save_location(isolated_locations.Location(
        id="warm_cafe", decor="暖色カフェ", camera_distance="medium",
    ))
    catalog = isolated_locations.build_location_catalog()
    assert [c["id"] for c in catalog] == ["home_office", "warm_cafe"]
    assert catalog[0]["decor"] == "北欧風"
    assert catalog[0]["camera_distance"] == "medium-close"


def test_build_location_catalog_empty_when_no_locations(isolated_locations):
    """ロケが 1 件も無ければ空 list を返す。"""
    assert isolated_locations.build_location_catalog() == []


def test_build_location_catalog_skips_broken_json(isolated_locations, tmp_path):
    """壊れた json は skip し、正常なロケだけ返す。"""
    isolated_locations.save_location(isolated_locations.Location(id="good"))
    bad = tmp_path / "locations" / "broken.json"
    with open(bad, "w") as f:
        f.write("{ not valid json")
    catalog = isolated_locations.build_location_catalog()
    assert [c["id"] for c in catalog] == ["good"]
