import pytest

import scene_gen


@pytest.fixture
def characters_dir(tmp_path, monkeypatch):
    chars = tmp_path / "characters"
    chars.mkdir()
    monkeypatch.setattr(scene_gen.config, "CHARACTERS_DIR", str(chars))
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
