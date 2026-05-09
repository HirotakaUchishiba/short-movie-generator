#!/usr/bin/env bash
# Install launchd job for daily YouTube metrics fetch.
#
# Usage:
#   bash tools/launchd/install.sh                  # 毎日 09:00 起動
#   bash tools/launchd/install.sh --hour 18        # 毎日 18:00 起動
#   bash tools/launchd/install.sh --hour 9 --minute 30
#
# Idempotent: 既存の同名ジョブは unload してから再登録する。

set -euo pipefail

LABEL="com.shortmoviegenerator.fetch-metrics"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${SCRIPT_DIR}/${LABEL}.plist.template"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"

HOUR=9
MINUTE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hour) HOUR="$2"; shift 2 ;;
    --minute) MINUTE="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ ! -f "${TEMPLATE}" ]]; then
  echo "template not found: ${TEMPLATE}" >&2
  exit 1
fi

PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "python3 が見つかりません (= command -v python3)" >&2
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents"
mkdir -p "${PROJECT_ROOT}/data"

if launchctl list 2>/dev/null | grep -q "${LABEL}"; then
  echo "[info] 既存ジョブを unload: ${LABEL}"
  launchctl unload "${TARGET}" 2>/dev/null || true
fi

sed \
  -e "s|{{PROJECT_ROOT}}|${PROJECT_ROOT}|g" \
  -e "s|{{PYTHON_BIN}}|${PYTHON_BIN}|g" \
  -e "s|{{HOUR}}|${HOUR}|g" \
  -e "s|{{MINUTE}}|${MINUTE}|g" \
  "${TEMPLATE}" > "${TARGET}"

launchctl load "${TARGET}"

printf '[install] %s\n' "${TARGET}"
printf '[install] 毎日 %02d:%02d に scripts/fetch_metrics.py --platform youtube を起動\n' "${HOUR}" "${MINUTE}"
printf '[install] python : %s\n' "${PYTHON_BIN}"
printf '[install] cwd    : %s\n' "${PROJECT_ROOT}"
printf '[install] log    : %s/data/launchd_fetch_metrics.{out,err}.log\n' "${PROJECT_ROOT}"
printf '[install] status : launchctl list | grep %s\n' "${LABEL}"
printf '[install] 即時実行 (= テスト) : launchctl start %s\n' "${LABEL}"
