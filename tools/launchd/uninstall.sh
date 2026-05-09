#!/usr/bin/env bash
# Remove launchd job for daily YouTube metrics fetch.

set -euo pipefail

LABEL="com.shortmoviegenerator.fetch-metrics"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [[ -f "${TARGET}" ]]; then
  launchctl unload "${TARGET}" 2>/dev/null || true
  rm -f "${TARGET}"
  echo "[uninstall] removed ${TARGET}"
else
  echo "[uninstall] not installed: ${TARGET}"
fi
