"""se_library の catalog load / list / resolve_se_path / se_by_category のテスト。"""
import json

import pytest

import config
import se_library


@pytest.fixture
def isolated_se(tmp_path, monkeypatch):
    se_dir = tmp_path / "se"
    se_dir.mkdir()
    catalog = tmp_path / "se_catalog.json"
    monkeypatch.setattr(config, "SE_DIR", str(se_dir))
    monkeypatch.setattr(config, "SE_CATALOG_PATH", str(catalog))
    return se_dir, catalog


def _write_catalog(catalog, entries):
    catalog.write_text(json.dumps(entries), encoding="utf-8")


def test_load_catalog_missing_returns_empty(isolated_se):
    assert se_library.load_catalog() == []


def test_load_catalog_broken_returns_empty(isolated_se):
    _, catalog = isolated_se
    catalog.write_text("{not json", encoding="utf-8")
    assert se_library.load_catalog() == []


def test_resolve_none_returns_none(isolated_se):
    assert se_library.resolve_se_path(None) is None
    assert se_library.resolve_se_path("") is None


def test_resolve_existing(isolated_se):
    se_dir, catalog = isolated_se
    (se_dir / "a.mp3").write_bytes(b"x")
    _write_catalog(catalog, [{"id": "a", "file": "a.mp3", "category": "reaction"}])
    p = se_library.resolve_se_path("a")
    assert p is not None and p.endswith("a.mp3")


def test_resolve_missing_file_returns_none(isolated_se):
    _, catalog = isolated_se
    _write_catalog(
        catalog, [{"id": "a", "file": "ghost.mp3", "category": "reaction"}])
    assert se_library.resolve_se_path("a") is None


def test_resolve_unknown_id_returns_none(isolated_se):
    _, catalog = isolated_se
    _write_catalog(catalog, [{"id": "a", "file": "a.mp3", "category": "reaction"}])
    assert se_library.resolve_se_path("nope") is None


def test_list_se_only_existing_files(isolated_se):
    se_dir, catalog = isolated_se
    (se_dir / "a.mp3").write_bytes(b"x")
    _write_catalog(catalog, [
        {"id": "a", "file": "a.mp3", "category": "reaction", "license": "CC0"},
        {"id": "b", "file": "ghost.mp3", "category": "sting"},  # 実ファイルなし
    ])
    out = se_library.list_se()
    assert [t["id"] for t in out] == ["a"]
    assert out[0]["license"] == "CC0"
    assert out[0]["category"] == "reaction"


def test_se_by_category_only_existing(isolated_se):
    se_dir, catalog = isolated_se
    (se_dir / "r.mp3").write_bytes(b"x")
    (se_dir / "t.mp3").write_bytes(b"x")
    _write_catalog(catalog, [
        {"id": "r", "file": "r.mp3", "category": "reaction"},
        {"id": "t", "file": "t.mp3", "category": "transition"},
        {"id": "ghost", "file": "ghost.mp3", "category": "reaction"},  # ファイルなし
    ])
    assert [t.id for t in se_library.se_by_category("reaction")] == ["r"]
    assert [t.id for t in se_library.se_by_category("transition")] == ["t"]
    assert se_library.se_by_category("nope") == []


def test_load_catalog_skips_entries_without_id(isolated_se):
    _, catalog = isolated_se
    _write_catalog(catalog, [{"id": "a", "file": "a.mp3"}, {"file": "noid.mp3"}])
    tracks = se_library.load_catalog()
    assert [t.id for t in tracks] == ["a"]
