"""Phase 4: IMPROVEMENT_STRATEGY の起動時 validate のテスト。"""
from __future__ import annotations

import importlib
import warnings


def _reload_config():
    """config パッケージと、env を読む子モジュールを reload する。

    config/__init__.py だけ reload しても `from config.qa import ...` の
    既存 binding は子モジュールの初回ロード時の値を保持する。env を切り替え
    たい test では子モジュール側の reload が必要。
    """
    import config.qa  # noqa: F401
    importlib.reload(__import__("config.qa", fromlist=["_"]))
    import config
    importlib.reload(config)
    return config


def test_invalid_improvement_strategy_falls_back_to_baseline(monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_STRATEGY", "not_a_real_strategy")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = _reload_config()
    assert config.IMPROVEMENT_STRATEGY == "baseline"
    # 警告が 1 件以上発火
    assert any(issubclass(w.category, RuntimeWarning) and
               "IMPROVEMENT_STRATEGY" in str(w.message) for w in caught)


def test_valid_improvement_strategy_kept(monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_STRATEGY", "active")
    config = _reload_config()
    assert config.IMPROVEMENT_STRATEGY == "active"


def test_default_is_baseline(monkeypatch):
    monkeypatch.delenv("IMPROVEMENT_STRATEGY", raising=False)
    config = _reload_config()
    assert config.IMPROVEMENT_STRATEGY == "baseline"


def test_production_human_gate_default_enabled(monkeypatch):
    monkeypatch.delenv("PRODUCTION_HUMAN_GATE_ENABLED", raising=False)
    config = _reload_config()
    assert config.PRODUCTION_HUMAN_GATE_ENABLED is True


def test_production_human_gate_can_be_disabled(monkeypatch):
    monkeypatch.setenv("PRODUCTION_HUMAN_GATE_ENABLED", "0")
    config = _reload_config()
    assert config.PRODUCTION_HUMAN_GATE_ENABLED is False
