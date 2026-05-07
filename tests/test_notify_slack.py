"""Phase 1: notify_slack の単体テスト。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_notify_skipped_when_webhook_empty(monkeypatch, caplog):
    import config
    monkeypatch.setattr(config, "SLACK_WEBHOOK_URL", "")
    from notify.slack import notify_slack
    with caplog.at_level("INFO"):
        ok = notify_slack("error", "test message")
    assert ok is False
    assert any("webhook 未設定" in r.message for r in caplog.records)


def test_notify_posts_when_webhook_set(monkeypatch):
    import config
    monkeypatch.setattr(config, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    fake_resp = MagicMock(status_code=200)
    fake_resp.raise_for_status = MagicMock()

    from notify import slack as _slack
    with patch.object(_slack, "__name__", _slack.__name__):
        with patch("requests.post", return_value=fake_resp) as p:
            ok = _slack.notify_slack("info", "deploy ok",
                                      context={"ts": "20260508_120000"})
    assert ok is True
    p.assert_called_once()
    payload = p.call_args.kwargs["json"]
    assert "INFO" in payload["text"]
    assert "deploy ok" in payload["text"]
    assert "ts" in payload["text"]
    assert "20260508_120000" in payload["text"]


def test_notify_returns_false_on_network_error(monkeypatch, caplog):
    import config
    monkeypatch.setattr(config, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    with patch("requests.post", side_effect=RuntimeError("network down")):
        from notify.slack import notify_slack
        with caplog.at_level("WARNING"):
            ok = notify_slack("error", "boom")
    assert ok is False
    assert any("通知失敗" in r.message for r in caplog.records)


def test_notify_no_context_omits_bullet(monkeypatch):
    import config
    monkeypatch.setattr(config, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    fake_resp = MagicMock(status_code=200, raise_for_status=MagicMock())
    with patch("requests.post", return_value=fake_resp) as p:
        from notify.slack import notify_slack
        notify_slack("warning", "message only")
    text = p.call_args.kwargs["json"]["text"]
    assert "•" not in text
