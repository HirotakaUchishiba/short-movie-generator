"""Phase 6: e2e_ui_check のサーバ/ブラウザ非依存ユニット部分のテスト。

実 E2E (サーバ + chromium 起動) は重いので CI 非対象。ここでは純粋ロジック
(_wait_port) のみ検証する。実 E2E は scripts/e2e_ui_check.py の直接実行で行う。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "e2e_ui_check.py"
    spec = importlib.util.spec_from_file_location("e2e_ui_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_wait_port_returns_false_for_closed_port():
    mod = _load_module()
    # 1 番ポートは通常閉じている → timeout 1s で False を返す
    assert mod._wait_port("127.0.0.1", 1, 1) is False


def test_module_exposes_run_and_main():
    mod = _load_module()
    assert callable(mod.run)
    assert callable(mod.main)
