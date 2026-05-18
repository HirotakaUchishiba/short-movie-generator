"""auto_loop / cron のコスト上限と暴走防止 gate (= Phase 1 制御群)。

config/__init__.py から段階分割 (= §3.1.4-b)。`scripts/auto_loop.py` /
cron 経路で「これ以上は止める」判定に使う soft limit / hard cap を集約する。
Phase 4 の publish gate (PRODUCTION_HUMAN_GATE_ENABLED) は内容的に近いが
qa.py 側 (= bandit / human gate 系) で扱う。
"""

import os

DAILY_COST_CAP_USD = float(os.getenv("DAILY_COST_CAP_USD", "20"))
MONTHLY_COST_CAP_USD = float(os.getenv("MONTHLY_COST_CAP_USD", "300"))
DAILY_VIDEO_CAP = int(os.getenv("DAILY_VIDEO_CAP", "5"))

# auto_loop が unlisted 以外で publish するのを許すかの gate。
# Phase 4 までは "0" 固定 (= unlisted / private 強制)。
AUTO_LOOP_ALLOW_PUBLIC = os.getenv("AUTO_LOOP_ALLOW_PUBLIC", "0") in ("1", "true", "True")

# Slack Incoming Webhook (= 失敗 / cap 抵触時の通知先)。空ならスキップ。
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip()

# auto_loop の各 stage が「これ以上かかったら遅すぎ」と判定する soft limit。
# stage runner 自体は中断せず、超過時に Slack に warning を流すだけの観測用。
# 旧名 AUTO_LOOP_STAGE_TIMEOUT_SEC は env / コードから廃止 (= 名前が "timeout" だ
# と hard 中断を期待されるため、実体に合わせて SOFT_LIMIT に統一)。
AUTO_LOOP_STAGE_SOFT_LIMIT_SEC = int(
    os.getenv("AUTO_LOOP_STAGE_SOFT_LIMIT_SEC", "1800"))
