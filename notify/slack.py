"""Phase 1: Slack Incoming Webhook 通知。

`SLACK_WEBHOOK_URL` が空なら全 call が no-op (= dev 環境で try/except 不要)。
本番 cron で auto_loop の失敗 / cap 抵触 / kill-switch 発火を流す。
"""
from __future__ import annotations

import logging
from typing import Literal

import config

logger = logging.getLogger(__name__)

Level = Literal["info", "warning", "error", "critical"]

_LEVEL_ICON = {
    "info": ":information_source:",
    "warning": ":warning:",
    "error": ":x:",
    "critical": ":rotating_light:",
}


def notify_slack(
    level: Level,
    message: str,
    *,
    context: dict | None = None,
    timeout_sec: float = 10.0,
) -> bool:
    """Slack に 1 件 post する。

    Args:
        level: 表示色 / icon の選択。
        message: 本文 (= 1 行サマリ)。
        context: 補助情報。``• key: value`` の形で本文に追記される。
        timeout_sec: HTTP timeout。

    Returns:
        投稿成功なら True、webhook 未設定 / network 失敗なら False。例外は raise しない。
    """
    webhook = config.SLACK_WEBHOOK_URL
    if not webhook:
        logger.info("[slack] webhook 未設定のためスキップ: [%s] %s",
                    level, message[:120])
        return False

    icon = _LEVEL_ICON.get(level, "")
    text = f"{icon} *[{level.upper()}]* {message}".strip()
    if context:
        ctx_lines = "\n".join(f"• `{k}`: {v}" for k, v in context.items())
        text = f"{text}\n{ctx_lines}"

    try:
        import requests
        r = requests.post(webhook, json={"text": text}, timeout=timeout_sec)
        r.raise_for_status()
    except Exception as e:
        logger.warning("[slack] 通知失敗 ([%s] %s): %s",
                       level, message[:60], e)
        return False
    return True
