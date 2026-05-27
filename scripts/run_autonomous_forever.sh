#!/usr/bin/env bash
# 24h 常駐ラッパー: STOP ファイルが無い限り autonomous_runner を --drain で回し続ける。
#
#   bash scripts/run_autonomous_forever.sh [SLEEP_SEC]   # 既定 300s 間隔
#
# 各サイクルで autonomous_runner.py --drain がキューを空になるまで消化して exit し、
# SLEEP 後にまた起動する (= 新規 URL がキューに積まれていれば処理される)。
#
# 安全装置 (いずれも runner / auto_loop / cost_tracking 側が担保):
#   - 予算上限:    config.DAILY_COST_CAP_USD / MONTHLY_COST_CAP_USD / DAILY_VIDEO_CAP
#   - kill switch: プロジェクト直下に AUTONOMOUS_STOP を作成 (touch AUTONOMOUS_STOP) で停止
#   - 通知:        notify_slack
#
# 本ラッパー自体は「定期起動 + STOP 監視」だけを行う薄い層。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SLEEP_SEC="${1:-300}"
STOP_FILE="$ROOT/AUTONOMOUS_STOP"

echo "[autonomous] forever loop start (sleep=${SLEEP_SEC}s, stop_file=${STOP_FILE})"
while true; do
  if [ -f "$STOP_FILE" ]; then
    echo "[autonomous] STOP file present -> exit"
    break
  fi
  # --drain: キューを空になるまで処理して終了。budget 超過 / STOP は runner が見て止める。
  python3 scripts/autonomous_runner.py --drain \
    || echo "[autonomous] runner exited non-zero (continuing to next cycle)"
  sleep "$SLEEP_SEC"
done
