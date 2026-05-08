"""auto_loop からの通知系 (Phase 1)。Slack のみ。

将来 PagerDuty / メール等を足す場合も `notify_<channel>` を増やす方針で、
auto_loop からは facade `notify_failure` / `notify_cap` 等を経由する。
"""
from notify.slack import notify_slack

__all__ = ["notify_slack"]
