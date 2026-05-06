"""cost_tracking.pricebook の単体テスト (外部 JSON 読み込み + 環境変数上書き)。"""
from __future__ import annotations

import json

import pytest

from cost_tracking import pricebook


@pytest.fixture
def tmp_pricebook(tmp_path, monkeypatch):
    book = {
        "version": 1,
        "jpy_per_usd": 145.0,
        "providers": {
            "anthropic": {
                "claude-opus-4-7": {
                    "input_per_mtok": 15.0,
                    "output_per_mtok": 75.0,
                    "source": "https://example.test",
                },
            },
            "google": {"imagen-3.0": {"usd_per_image": 0.04}},
        },
    }
    path = tmp_path / "pricebook.json"
    path.write_text(json.dumps(book), encoding="utf-8")
    monkeypatch.setenv("PRICEBOOK_PATH", str(path))
    monkeypatch.delenv("JPY_PER_USD", raising=False)
    return path


def test_load_returns_full_book(tmp_pricebook) -> None:
    book = pricebook.load()
    assert book["version"] == 1
    assert "anthropic" in book["providers"]


def test_get_unit_prices_strips_source(tmp_pricebook) -> None:
    prices = pricebook.get_unit_prices("anthropic", "claude-opus-4-7")
    assert prices == {"input_per_mtok": 15.0, "output_per_mtok": 75.0}
    assert "source" not in prices


def test_get_unit_prices_unknown_provider_raises(tmp_pricebook) -> None:
    with pytest.raises(KeyError, match="unknown provider"):
        pricebook.get_unit_prices("unknown_provider", "x")


def test_get_unit_prices_unknown_model_raises(tmp_pricebook) -> None:
    with pytest.raises(KeyError, match="unknown model"):
        pricebook.get_unit_prices("anthropic", "claude-haiku-1")


def test_jpy_per_usd_reads_from_pricebook(tmp_pricebook) -> None:
    assert pricebook.jpy_per_usd() == 145.0


def test_jpy_per_usd_env_overrides_pricebook(tmp_pricebook, monkeypatch) -> None:
    monkeypatch.setenv("JPY_PER_USD", "160")
    assert pricebook.jpy_per_usd() == 160.0


def test_list_models_returns_registered_keys(tmp_pricebook) -> None:
    assert pricebook.list_models("anthropic") == ["claude-opus-4-7"]
    assert pricebook.list_models("google") == ["imagen-3.0"]
    assert pricebook.list_models("unregistered") == []


def test_load_missing_file_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PRICEBOOK_PATH", str(tmp_path / "nonexistent.json"))
    with pytest.raises(FileNotFoundError):
        pricebook.load()
