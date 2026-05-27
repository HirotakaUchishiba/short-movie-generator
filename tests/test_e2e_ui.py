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


def test_run_forwards_port_to_server_env(monkeypatch):
    import pytest
    pytest.importorskip("playwright")
    mod = _load_module()
    captured = {}

    class _FakePopen:
        def __init__(self, args, **kw):
            captured["env"] = kw.get("env", {})

        def send_signal(self, _sig):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(mod.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(mod, "_port_in_use", lambda h, p: False)
    monkeypatch.setattr(mod, "_wait_port", lambda h, p, t: False)
    rc = mod.run("/tmp/_e2e_x.png", 1, 6789)
    assert rc == 1  # _wait_port False で early return
    assert captured["env"].get("PREVIEW_PORT") == "6789"  # port が server に転送される
