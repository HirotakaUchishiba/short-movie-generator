"""analyze.character_meta の単体テスト (CharacterMeta dataclass + CRUD)。"""
import pytest

# このファイルは character_meta 本体の挙動を直接テストするので、
# conftest の `_stub_character_images` autouse fixture を opt-out する。
pytestmark = pytest.mark.real_characters_dir


@pytest.fixture
def isolated_characters(tmp_path, monkeypatch):
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "CHARACTERS_DIR", tmp_path / "characters")
    return cmeta_mod


def test_save_and_load_round_trip(isolated_characters):
    """voice meta は base id 単位で保存される (= resolved id を渡すと wardrobe を
    自動で剥がして base 単位で読む)。"""
    meta = isolated_characters.CharacterMeta(
        id="f1",
        voice_overrides={"voice_id": "v1", "stability": 0.4},
    )
    isolated_characters.save_character_meta(meta)
    # base id で load
    loaded = isolated_characters.load_character_meta("f1")
    assert loaded.id == "f1"
    # from_dict は voice_overrides 内の voice_id を top-level に正規化し overrides から除く
    assert loaded.voice_id == "v1"
    assert loaded.voice_overrides == {"stability": 0.4}
    # resolved id (base + wardrobe) で load しても同じ meta が返る
    loaded2 = isolated_characters.load_character_meta("f1__office")
    assert loaded2.id == "f1"
    assert loaded2.voice_id == "v1"
    assert loaded2.voice_overrides == {"stability": 0.4}


def test_save_rejects_wardrobe_suffix(isolated_characters):
    """meta.id に __wardrobe を含めると validation で reject される
    (= voice は base 単位で 1 つ)。"""
    meta = isolated_characters.CharacterMeta(id="f1__office")
    with pytest.raises(ValueError, match="BASE id"):
        isolated_characters.save_character_meta(meta)


def test_load_missing_returns_empty_meta(isolated_characters):
    """meta 未設定なら base id だけ持つ空 meta を返す。"""
    loaded = isolated_characters.load_character_meta("nope")
    assert loaded.id == "nope"
    assert loaded.voice_overrides == {}


def test_validate_requires_id(isolated_characters):
    meta = isolated_characters.CharacterMeta(id="")
    errors = meta.validate()
    assert any("id" in e for e in errors)


def test_invalid_id_blocked(isolated_characters):
    with pytest.raises(ValueError):
        isolated_characters.base_dir("../etc/passwd")


def test_split_resolved_id(isolated_characters):
    assert isolated_characters.split_resolved_id("f1__office") == ("f1", "office")
    assert isolated_characters.split_resolved_id("f1") == ("f1", None)


def test_image_path_resolves_nested(isolated_characters, tmp_path):
    base = isolated_characters.CHARACTERS_DIR / "f1"
    base.mkdir(parents=True)
    (base / "office.png").write_bytes(b"x")
    (base / "base.png").write_bytes(b"x")
    p1 = isolated_characters.image_path("f1__office")
    assert p1 is not None and p1.name == "office.png"
    p2 = isolated_characters.image_path("f1")
    assert p2 is not None and p2.name == "base.png"


def test_image_path_falls_back_to_flat(isolated_characters, tmp_path):
    """旧 flat レイアウト (= characters/<resolved>.png) も拾う (互換維持)。"""
    isolated_characters.CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    (isolated_characters.CHARACTERS_DIR / "legacy_id.png").write_bytes(b"x")
    p = isolated_characters.image_path("legacy_id")
    assert p is not None and p.name == "legacy_id.png"


def test_list_character_images_includes_wardrobe_variants(isolated_characters):
    base = isolated_characters.CHARACTERS_DIR / "f1"
    base.mkdir(parents=True)
    (base / "office.png").write_bytes(b"x")
    (base / "casual.png").write_bytes(b"x")
    (base / "base.png").write_bytes(b"x")
    (base / "preview.png").write_bytes(b"x")  # preview は除外
    ids = isolated_characters.list_character_images()
    assert sorted(ids) == ["f1", "f1__casual", "f1__office"]


def test_list_character_metas_alphabetical(isolated_characters):
    isolated_characters.save_character_meta(
        isolated_characters.CharacterMeta(id="zeta"),
    )
    isolated_characters.save_character_meta(
        isolated_characters.CharacterMeta(id="alpha"),
    )
    assert isolated_characters.list_character_metas() == ["alpha", "zeta"]


def test_delete_character_meta(isolated_characters):
    isolated_characters.save_character_meta(
        isolated_characters.CharacterMeta(id="a"),
    )
    assert isolated_characters.delete_character_meta("a") is True
    assert isolated_characters.delete_character_meta("a") is False


def test_appearance_round_trip(isolated_characters):
    """appearance は voice.json に保存/読込される。"""
    meta = isolated_characters.CharacterMeta(
        id="f1",
        voice_overrides={"voice_id": "v1"},
        appearance={"gender": "female", "age_range": "20s",
                    "description": "黒髪ロング"},
    )
    isolated_characters.save_character_meta(meta)
    loaded = isolated_characters.load_character_meta("f1")
    assert loaded.appearance == {
        "gender": "female", "age_range": "20s", "description": "黒髪ロング",
    }


def test_appearance_omitted_when_empty(isolated_characters):
    """appearance が空なら to_dict / voice.json に含まれない。"""
    import json
    meta = isolated_characters.CharacterMeta(id="f1")
    assert "appearance" not in meta.to_dict()
    isolated_characters.save_character_meta(meta)
    p = isolated_characters.CHARACTERS_DIR / "f1" / "voice.json"
    assert "appearance" not in json.loads(p.read_text())


def test_voice_id_round_trip(isolated_characters):
    """voice_id は voice.json に保存/読込される。"""
    meta = isolated_characters.CharacterMeta(
        id="f1",
        voice_id="0ptCJp0xgdabdcpVtCB5",
        voice_overrides={"stability": 0.4},
    )
    isolated_characters.save_character_meta(meta)
    loaded = isolated_characters.load_character_meta("f1")
    assert loaded.voice_id == "0ptCJp0xgdabdcpVtCB5"
    assert loaded.voice_overrides == {"stability": 0.4}


def test_voice_id_omitted_when_empty(isolated_characters):
    """voice_id が None/空文字なら to_dict / voice.json に含まれない (= 旧 file 互換)。"""
    import json
    meta = isolated_characters.CharacterMeta(id="f1")
    assert "voice_id" not in meta.to_dict()
    isolated_characters.save_character_meta(meta)
    p = isolated_characters.CHARACTERS_DIR / "f1" / "voice.json"
    assert "voice_id" not in json.loads(p.read_text())


def test_voice_id_legacy_file_loads_with_none(isolated_characters):
    """voice_id field 不在の旧 voice.json は voice_id=None で読まれる (= forward compat)。"""
    import json
    base = isolated_characters.CHARACTERS_DIR / "f1"
    base.mkdir(parents=True)
    (base / "voice.json").write_text(json.dumps({
        "id": "f1", "voice_overrides": {"stability": 0.4},
    }))
    loaded = isolated_characters.load_character_meta("f1")
    assert loaded.voice_id is None
    assert loaded.voice_overrides == {"stability": 0.4}


def test_voice_id_validation_rejects_non_string(isolated_characters):
    """voice_id が str 以外 (= int/dict) なら validate がエラーを返す。"""
    meta = isolated_characters.CharacterMeta(id="f1", voice_id=123)
    errors = meta.validate()
    assert any("voice_id" in e for e in errors)


def test_build_character_catalog_groups_by_base(isolated_characters):
    """build_character_catalog は画像を持つ resolved id を base 単位にまとめ、
    base の appearance を添える。"""
    base = isolated_characters.CHARACTERS_DIR / "f1"
    base.mkdir(parents=True)
    (base / "base.png").write_bytes(b"x")
    (base / "office.png").write_bytes(b"x")
    isolated_characters.save_character_meta(isolated_characters.CharacterMeta(
        id="f1", appearance={"gender": "female"},
    ))
    m1 = isolated_characters.CHARACTERS_DIR / "m1"
    m1.mkdir(parents=True)
    (m1 / "base.png").write_bytes(b"x")

    catalog = isolated_characters.build_character_catalog()
    assert [c["id"] for c in catalog] == ["f1", "m1"]
    assert catalog[0]["appearance"] == {"gender": "female"}
    assert catalog[0]["refs"] == ["f1", "f1__office"]
    # appearance 未設定の m1 は空 dict
    assert catalog[1]["appearance"] == {}
    assert catalog[1]["refs"] == ["m1"]


def test_build_character_catalog_empty_when_no_characters(isolated_characters):
    isolated_characters.CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    assert isolated_characters.build_character_catalog() == []


def test_build_character_catalog_skips_broken_voice_json(isolated_characters):
    """壊れた voice.json は appearance 空で続行する。"""
    base = isolated_characters.CHARACTERS_DIR / "f1"
    base.mkdir(parents=True)
    (base / "base.png").write_bytes(b"x")
    (base / "voice.json").write_text("{ broken json")
    catalog = isolated_characters.build_character_catalog()
    assert len(catalog) == 1
    assert catalog[0]["id"] == "f1"
    assert catalog[0]["appearance"] == {}
