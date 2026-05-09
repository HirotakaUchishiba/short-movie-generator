"""publish() 直前の channel guard (= _confirm_publish_channel) の挙動テスト。"""
import pytest


def _stub_channel_label(**override) -> dict:
    base = {
        "profile": "(default)",
        "aud": "client.example.com",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    }
    base.update(override)
    return base


def test_confirm_publish_channel_skip_returns_none_without_io() -> None:
    from final_import.publish import _confirm_publish_channel
    assert _confirm_publish_channel(skip=True) is None


def test_confirm_publish_channel_yes_proceeds(monkeypatch) -> None:
    from final_import import publish

    monkeypatch.setattr(
        "platform_clients.youtube._resolve_channel_label",
        lambda: _stub_channel_label(title="Brand", channel_id="UCxyz"),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    assert publish._confirm_publish_channel(skip=False) is None


def test_confirm_publish_channel_yes_uppercase_proceeds(monkeypatch) -> None:
    from final_import import publish

    monkeypatch.setattr(
        "platform_clients.youtube._resolve_channel_label",
        lambda: _stub_channel_label(),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")
    assert publish._confirm_publish_channel(skip=False) is None


def test_confirm_publish_channel_no_aborts_with_systemexit(monkeypatch) -> None:
    from final_import import publish

    monkeypatch.setattr(
        "platform_clients.youtube._resolve_channel_label",
        lambda: _stub_channel_label(),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    with pytest.raises(SystemExit, match="ユーザーキャンセル"):
        publish._confirm_publish_channel(skip=False)


def test_confirm_publish_channel_empty_answer_aborts(monkeypatch) -> None:
    from final_import import publish

    monkeypatch.setattr(
        "platform_clients.youtube._resolve_channel_label",
        lambda: _stub_channel_label(),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    with pytest.raises(SystemExit):
        publish._confirm_publish_channel(skip=False)


def test_confirm_publish_channel_non_tty_raises_runtimeerror(monkeypatch) -> None:
    from final_import import publish

    monkeypatch.setattr(
        "platform_clients.youtube._resolve_channel_label",
        lambda: _stub_channel_label(),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(RuntimeError, match="tty"):
        publish._confirm_publish_channel(skip=False)
