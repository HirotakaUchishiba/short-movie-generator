# routes パッケージ — preview_server.py を Blueprint 分割するための受け皿。
#
# 進行状況 (= 2026-05-18 時点):
#   ✓ routes/_helpers.py — shared util (= api_error / safe_join / is_valid_ts)
#   ✓ routes/cost.py — /api/cost/*
#   ✓ routes/projects.py — /api/projects (一覧 + 作成 + 詳細)
#   ✓ routes/stages.py — /api/projects/<ts>/{run-next,approve,reject,regen}
#   ✓ routes/assets.py — /asset/* + /api/projects/<ts>/{screenplay,bg,...}
#   ✓ routes/final_publish.py — /api/projects/<ts>/{final*,publish*}
#   ✓ routes/config.py — /api/config
#   ✓ routes/intent_catalog.py — /api/intent-catalog
#   ✓ routes/intent_suggestions.py — /api/intent-suggestions
#   ✓ routes/clip_library.py — /api/clip-library/*
#
# 残 (= preview_server.py 内に直書きされたまま):
#   TODO routes/screenplay.py — /api/projects/<ts>/{abstract,line,...} の
#                                screenplay 編集系 endpoint (= patch / save)
#   TODO routes/analyze.py — /api/analyze-jobs/* (= job 管理 + cache 系)
#
# 移行は 1 Blueprint = 1 PR を目安に、その都度全テスト pass を保つ。
# 残 endpoint の jsonify({"error":...}) (= 約 70 箇所) は api_error() 経由に
# 統一する (= 計画書 §3.1.2-b)。routes/projects.py の 4 箇所は §3.7-a で
# 移行済 (= PROJECT_* prefix)。
