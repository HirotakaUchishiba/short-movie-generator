"""Phase 1: YouTube upload の AUTO_LOOP_ALLOW_PUBLIC gate のテスト。"""
from __future__ import annotations


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


def test_resolve_privacy_case_insensitive_blocks_mixed_case_public(
    monkeypatch, caplog,
):
    """`"Public"` / `"PUBLIC"` 等の casing でも降格を発火させる
    (= CLI choices で守られていない呼び出し経路への防御深度)。"""
    import config
    monkeypatch.setattr(config, "AUTO_LOOP_ALLOW_PUBLIC", False)
    with caplog.at_level("WARNING"):
        assert _resolve_privacy("Public") == "unlisted"
        assert _resolve_privacy("PUBLIC") == "unlisted"
    # opt-in 中は降格しない (= 出力は lowercase 正規化される)
    monkeypatch.setattr(config, "AUTO_LOOP_ALLOW_PUBLIC", True)
    assert _resolve_privacy("Public") == "public"


def test_resolve_privacy_normalizes_casing_for_other_values(monkeypatch):
    """unlisted / private も casing 正規化される (= API への lowercase 強制)。"""
    import config
    monkeypatch.setattr(config, "AUTO_LOOP_ALLOW_PUBLIC", False)
    assert _resolve_privacy("Unlisted") == "unlisted"
    assert _resolve_privacy("PRIVATE") == "private"


def test_resolve_privacy_handles_empty_and_whitespace(monkeypatch):
    """空文字 / whitespace は無傷で返す (= API 側で型エラーになるのが
    自然な挙動。privacy gate の責務は "public 降格" だけ)。"""
    import config
    monkeypatch.setattr(config, "AUTO_LOOP_ALLOW_PUBLIC", False)
    # 空 / 空白だけは 元値で返る (= 後続 API call で reject される想定)
    assert _resolve_privacy("") == ""
    assert _resolve_privacy("  ") == "  "
