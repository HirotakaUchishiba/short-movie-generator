"""Phase 1: YouTube upload の AUTO_LOOP_ALLOW_PUBLIC gate のテスト。"""
from __future__ import annotations

import pytest

from platform_clients.youtube import _resolve_privacy


def test_resolve_privacy_blocks_public_by_default(monkeypatch, caplog):
    import config
    monkeypatch.setattr(config, "AUTO_LOOP_ALLOW_PUBLIC", False)
    with caplog.at_level("WARNING"):
        assert _resolve_privacy("public") == "unlisted"
    assert any("AUTO_LOOP_ALLOW_PUBLIC=0" in r.message for r in caplog.records)


def test_resolve_privacy_allows_public_when_opt_in(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTO_LOOP_ALLOW_PUBLIC", True)
    assert _resolve_privacy("public") == "public"


def test_resolve_privacy_passes_through_unlisted(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTO_LOOP_ALLOW_PUBLIC", False)
    assert _resolve_privacy("unlisted") == "unlisted"


def test_resolve_privacy_passes_through_private(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTO_LOOP_ALLOW_PUBLIC", False)
    assert _resolve_privacy("private") == "private"
