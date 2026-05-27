"""bgm_library の catalog load / list / resolve_bgm_path のテスト。"""
import json

import pytest

import bgm_library
import config


@pytest.fixture
def isolated_bgm(tmp_path, monkeypatch):
    bgm_dir = tmp_path / "bgm"
    bgm_dir.mkdir()
    catalog = tmp_path / "bgm_catalog.json"
    monkeypatch.setattr(config, "BGM_DIR", str(bgm_dir))
    monkeypatch.setattr(config, "BGM_CATALOG_PATH", str(catalog))
    return bgm_dir, catalog


def _write_catalog(catalog, entries):
    catalog.write_text(json.dumps(entries), encoding="utf-8")


def test_load_catalog_missing_returns_empty(isolated_bgm):
    assert bgm_library.load_catalog() == []


def test_load_catalog_broken_returns_empty(isolated_bgm):
    _, catalog = isolated_bgm
    catalog.write_text("{not json", encoding="utf-8")
    assert bgm_library.load_catalog() == []


def test_resolve_none_returns_none(isolated_bgm):
    assert bgm_library.resolve_bgm_path("none") is None
    assert bgm_library.resolve_bgm_path(None) is None
    assert bgm_library.resolve_bgm_path("") is None


def test_resolve_existing(isolated_bgm):
    bgm_dir, catalog = isolated_bgm
    (bgm_dir / "a.mp3").write_bytes(b"x")
    _write_catalog(catalog, [{"id": "a", "file": "a.mp3"}])
    p = bgm_library.resolve_bgm_path("a")
    assert p is not None and p.endswith("a.mp3")


def test_resolve_missing_file_returns_none(isolated_bgm):
    _, catalog = isolated_bgm
    _write_catalog(catalog, [{"id": "a", "file": "ghost.mp3"}])
    assert bgm_library.resolve_bgm_path("a") is None


def test_resolve_unknown_id_returns_none(isolated_bgm):
    _, catalog = isolated_bgm
    _write_catalog(catalog, [{"id": "a", "file": "a.mp3"}])
    assert bgm_library.resolve_bgm_path("nope") is None


def test_list_bgm_only_existing_files(isolated_bgm):
    bgm_dir, catalog = isolated_bgm
    (bgm_dir / "a.mp3").write_bytes(b"x")
    _write_catalog(catalog, [
        {"id": "a", "file": "a.mp3", "license": "CC0", "mood": "calm"},
        {"id": "b", "file": "ghost.mp3"},  # 実ファイルなし → list に出ない
    ])
    out = bgm_library.list_bgm()
    assert [t["id"] for t in out] == ["a"]
    assert out[0]["license"] == "CC0"
    assert out[0]["mood"] == "calm"


def test_load_catalog_skips_entries_without_id(isolated_bgm):
    _, catalog = isolated_bgm
    _write_catalog(catalog, [{"id": "a", "file": "a.mp3"}, {"file": "noid.mp3"}])
    tracks = bgm_library.load_catalog()
    assert [t.id for t in tracks] == ["a"]
