import pytest

import scene_gen


@pytest.fixture
def characters_dir(tmp_path, monkeypatch):
    chars = tmp_path / "characters"
    chars.mkdir()
    # 画像解決は character_meta.image_path に委譲されるため、そちらの
    # CHARACTERS_DIR を差し替える (= config.CHARACTERS_DIR は import 時に
    # Path 化されて character_meta へ固定コピーされるので config 側の
    # monkeypatch は image_path に届かない)。
    from analyze import character_meta as cmeta
    monkeypatch.setattr(cmeta, "CHARACTERS_DIR", chars)
    return chars


def test_resolve_uses_default_when_key_absent(characters_dir, monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "DEFAULT_CHARACTER_REFS", ["protagonist"])
    (characters_dir / "protagonist.png").write_bytes(b"fake")
    result = scene_gen._resolve_character_refs({"background_prompt": "foo"})
    assert len(result) == 1
    assert result[0].endswith("protagonist.png")


def test_resolve_returns_empty_when_refs_explicitly_empty(characters_dir, monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "DEFAULT_CHARACTER_REFS", ["protagonist"])
    (characters_dir / "protagonist.png").write_bytes(b"fake")
    result = scene_gen._resolve_character_refs(
        {"identity": {"character_refs": []}}
    )
    assert result == []


def test_resolve_returns_empty_when_refs_missing(characters_dir) -> None:
    result = scene_gen._resolve_character_refs(
        {"identity": {"character_refs": ["missing"]}}
    )
    assert result == []


def test_resolve_returns_paths_for_existing(characters_dir) -> None:
    ref = characters_dir / "protagonist.png"
    ref.write_bytes(b"fake")
    result = scene_gen._resolve_character_refs(
        {"identity": {"character_refs": ["protagonist"]}}
    )
    assert len(result) == 1
    assert result[0].endswith("protagonist.png")


def test_resolve_skips_missing_but_keeps_existing(characters_dir) -> None:
    (characters_dir / "hero.png").write_bytes(b"fake")
    result = scene_gen._resolve_character_refs(
        {"identity": {"character_refs": ["hero", "missing", "still_missing"]}}
    )
    assert len(result) == 1
    assert "hero" in result[0]


def test_resolve_preserves_order(characters_dir) -> None:
    (characters_dir / "a.png").write_bytes(b"a")
    (characters_dir / "b.png").write_bytes(b"b")
    result = scene_gen._resolve_character_refs(
        {"identity": {"character_refs": ["b", "a"]}}
    )
    assert result[0].endswith("b.png")
    assert result[1].endswith("a.png")


def test_resolve_nested_wardrobe(characters_dir) -> None:
    """resolved id <base>__<wardrobe> をネスト構造 <base>/<wardrobe>.png に解決。"""
    (characters_dir / "m1").mkdir()
    (characters_dir / "m1" / "office.png").write_bytes(b"png")
    result = scene_gen._resolve_character_refs(
        {"identity": {"character_refs": ["m1__office"]}}
    )
    assert len(result) == 1
    assert result[0].replace("\\", "/").endswith("m1/office.png")


def test_resolve_nested_base_when_no_wardrobe(characters_dir) -> None:
    """wardrobe 無しの base id は <base>/base.png に解決。"""
    (characters_dir / "m1").mkdir()
    (characters_dir / "m1" / "base.png").write_bytes(b"png")
    result = scene_gen._resolve_character_refs(
        {"identity": {"character_refs": ["m1"]}}
    )
    assert len(result) == 1
    assert result[0].replace("\\", "/").endswith("m1/base.png")
