#!/usr/bin/env bash
# auto_loop_queue.sh — data/auto_loop_queue.txt の先頭から 1 URL を取り出して
#                     auto_loop.py を 1 回だけ起動する。launchd / cron から呼ぶ前提。
#
# queue ファイル仕様:
#   - 1 行 1 URL (= yt-dlp 対応の動画 URL)
#   - 空行と `#` で始まる行は無視
#   - 取り出した行は data/auto_loop_done.txt に追記される
#
# license / privacy はここで決め打ち。プロジェクト方針に応じて調整。
#
# 例: data/auto_loop_queue.txt
#     # 2026-05 撮影分
#     https://www.youtube.com/watch?v=xxxxx
#     https://www.youtube.com/watch?v=yyyyy
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PYTHON="${PYTHON:-$(command -v python3)}"
QUEUE_FILE="${AUTO_LOOP_QUEUE_FILE:-$PROJECT_ROOT/data/auto_loop_queue.txt}"
DONE_FILE="${AUTO_LOOP_DONE_FILE:-$PROJECT_ROOT/data/auto_loop_done.txt}"
LICENSE="${AUTO_LOOP_LICENSE:-user_owned}"  # creative_commons / public_domain / user_owned
PRIVACY="${AUTO_LOOP_PRIVACY:-unlisted}"

cd "$PROJECT_ROOT"

if [[ ! -f "$QUEUE_FILE" ]]; then
    echo "[auto_loop_queue] queue file not found: $QUEUE_FILE" >&2
    exit 1
fi

# 先頭の有効行を 1 つ取り出す
url=""
while IFS= read -r line || [[ -n "$line" ]]; do
    trimmed="$(echo "$line" | sed -E 's/^[[:space:]]+//;s/[[:space:]]+$//')"
    if [[ -z "$trimmed" ]] || [[ "$trimmed" =~ ^# ]]; then
        continue
    fi
    url="$trimmed"
    break
done < "$QUEUE_FILE"

if [[ -z "$url" ]]; then
    echo "[auto_loop_queue] queue 空 — skip"
    exit 0
fi

# queue から先頭 1 行 (有効行) を消す
tmp_file="$(mktemp)"
removed=0
while IFS= read -r line || [[ -n "$line" ]]; do
    trimmed="$(echo "$line" | sed -E 's/^[[:space:]]+//;s/[[:space:]]+$//')"
    if [[ "$removed" -eq 0 ]] && [[ -n "$trimmed" ]] && [[ ! "$trimmed" =~ ^# ]]; then
        removed=1
        continue
    fi
    echo "$line"
done < "$QUEUE_FILE" > "$tmp_file"
mv "$tmp_file" "$QUEUE_FILE"

# done log に追記
echo "$(date -Iseconds) $url" >> "$DONE_FILE"

echo "[auto_loop_queue] running: $url"
exec "$PYTHON" "$PROJECT_ROOT/scripts/auto_loop.py" "$url" \
    --license "$LICENSE" --privacy "$PRIVACY"
