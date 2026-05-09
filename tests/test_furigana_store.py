from pathlib import Path

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("FURIGANA_DICT_PATH", str(tmp_path / "furigana.json"))
    import importlib
    import furigana_store
    importlib.reload(furigana_store)
    return tmp_path


def test_load_returns_empty_when_file_missing(isolated) -> None:
    import furigana_store
    assert furigana_store.load() == {}


def test_save_and_load_roundtrip(isolated) -> None:
    import furigana_store
    furigana_store.save({"納期間に": "のうきまに", "IT": "アイティー"})
    loaded = furigana_store.load()
    assert loaded == {"納期間に": "のうきまに", "IT": "アイティー"}


def test_merge_adds_new_entries(isolated) -> None:
    import furigana_store
    furigana_store.save({"IT": "アイティー"})
    result = furigana_store.merge({"PC": "ピーシー"})
    assert result == {"IT": "アイティー", "PC": "ピーシー"}


def test_merge_updates_existing_with_different_reading(isolated) -> None:
    import furigana_store
    furigana_store.save({"納期間": "のうきかん"})  # 誤読データ
    result = furigana_store.merge({"納期間": "のうきま"})  # 正しい読み
    assert result["納期間"] == "のうきま"


def test_merge_skips_empty(isolated) -> None:
    import furigana_store
    furigana_store.save({"IT": "アイティー"})
    result = furigana_store.merge({})
    assert result == {"IT": "アイティー"}


def test_collect_from_screenplay() -> None:
    import furigana_store
    sp = {
        "scenes": [
            {
                "lines": [
                    {"text": "a", "pronunciation_hints": {"納期": "のうき"}},
                    {"text": "b", "pronunciation_hints": {"IT": "アイティー"}},
                ],
            },
            {
                "lines": [
                    {"text": "c", "pronunciation_hints": {"納期": "のうき"}},  # 重複
                    {"text": "d"},
                ],
            },
        ],
    }
    out = furigana_store.collect_from_screenplay(sp)
    assert out == {"納期": "のうき", "IT": "アイティー"}


def test_collect_returns_empty_for_no_hints() -> None:
    import furigana_store
    sp = {"scenes": [{"lines": [{"text": "a"}]}]}
    assert furigana_store.collect_from_screenplay(sp) == {}
