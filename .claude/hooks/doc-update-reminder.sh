#!/bin/bash
# 主要モジュールを編集したとき、対応する設計 doc の更新を提案する PostToolUse hook。
# 設定: .claude/settings.json hooks.PostToolUse から呼ばれる。
# 入力: $CLAUDE_FILE_PATH (= Edit/Write の対象ファイルパス)
# 出力: stderr に reminder 文字列 (= Claude / user に見える形)
#
# 参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.10-b

file_path="${CLAUDE_FILE_PATH:-}"

if [ -z "$file_path" ]; then
    exit 0
fi

# 短いベース名で case 分岐 (= 絶対パス・相対パス両方に対応)
base=$(basename "$file_path")
dir=$(dirname "$file_path")

case "$file_path" in
    */analyze/*.py|*/compose.py)
        echo "💡 [doc-reminder] $base を編集しました。analyze / compose スキーマ変更があれば docs/abstract-screenplay-design.md の更新が必要か確認してください。" >&2
        ;;
    */scene_gen.py|*/staged_pipeline.py|*/preview_server.py|*/compositor.py)
        echo "💡 [doc-reminder] $base を編集しました。Stage 仕様変更があれば docs/developments/architecture.md / CLAUDE.md の更新が必要か確認してください。" >&2
        ;;
    */screenplay_validator.py|*/config.py)
        echo "💡 [doc-reminder] $base を編集しました。スキーマ / 用語変更があれば docs/developments/ubiquitous-language.md の更新が必要か確認してください。" >&2
        ;;
    */platform_clients/*.py|*/final_import/*.py|*/analytics/db.py)
        echo "💡 [doc-reminder] $base を編集しました。Stage 7-8 / publish 仕様変更があれば CLAUDE.md / docs/developments/architecture.md の更新が必要か確認してください。" >&2
        ;;
esac

exit 0
