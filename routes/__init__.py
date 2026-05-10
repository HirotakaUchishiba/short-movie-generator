# routes パッケージ — preview_server.py を Blueprint 分割するための受け皿。
#
# 段階的移行計画:
#   1. (済)  routes/_helpers.py で shared util 抽出
#   2. (TODO) routes/cost.py — /api/cost/* (= 5 routes、最も独立性が高い)
#   3. (TODO) routes/projects.py — /api/projects 一覧 + 作成
#   4. (TODO) routes/stages.py — /api/projects/<ts>/{run-next,approve,reject,regen}
#   5. (TODO) routes/assets.py — /asset/* と /api/projects/<ts>/{screenplay,bg,...}
#   6. (TODO) routes/final.py — /api/projects/<ts>/final*
#   7. (TODO) routes/publish.py — /api/projects/<ts>/{publish,publish-history}
#
# 移行は 1 Blueprint = 1 PR を目安に行い、その都度 1210+ 件の pytest を保つ。
