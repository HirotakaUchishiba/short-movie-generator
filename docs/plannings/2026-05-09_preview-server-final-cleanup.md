# preview_server.py 最終 cleanup — 残 routes 抽出と app.py rename

**date**: 2026-05-09 / **base branch**: `feat/preview-server-cleanup-roadmap`

`preview_server.py` の Blueprint 完全分割が大幅進捗した状態 (= 約 2400 →
約 1570 LOC) をさらに削減し、最終的に `app.py` (= Flask 起動と
Blueprint register のみの薄い entry point、~150 LOC) に集約する作業の
ロードマップ。

## ここまでの進捗 (= 8 PR 完了)

| PR  | Blueprint                               | 移管 routes 数 |
| --- | --------------------------------------- | -------------- |
| #86 | routes/\_helpers.py + stages/text_utils | (helpers のみ) |
| #87 | routes/cost.py                          | 5              |
| #89 | routes/analytics.py                     | 2              |
| #90 | routes/config.py                        | 5              |
| #91 | routes/projects.py                      | 3              |
| #92 | (job_runner.py 抽出)                    | (state)        |
| #93 | routes/stages.py                        | 4              |
| #94 | routes/final_publish.py                 | 7              |
| #95 | routes/assets.py                        | 11             |

合計 **37 routes** + helper / state を Blueprint 化済み。
preview_server.py は 2400 LOC → 1569 LOC (= 約 35% 削減)。

## 残作業 (= 4 PR 想定)

### PR-A: routes/screenplay.py (= /api/projects/<ts>/screenplay & 関連 PUT)

対象 routes:

- `PUT /api/projects/<ts>/screenplay` (= snapshot 上書き)
- `GET /api/projects/<ts>/screenplay/preview-text` (= TTS preview 用)
- `PATCH /api/projects/<ts>/screenplay/lines/<scene_idx>/<line_idx>`
- `PATCH /api/projects/<ts>/screenplay/scenes/<scene_idx>`
- `PUT /api/projects/<ts>/abstract` (= 抽象台本書き戻し)

依存:

- `screenplay_validator.validate_screenplay`
- `_screenplay_lock` (= staged_pipeline.screenplay_lock)
- `staged_pipeline.save_project_screenplay`

### PR-B: routes/cache.py (= bg / kling stage cache 操作)

対象 routes:

- `_StageCacheHandler` 共通フロー (= scan / use-cache / queue-fresh /
  rescan / decisions/bulk / generate-remaining / preview / blacklist /
  delete) を bg / kling 両 stage で 1 module に集約
- LOC: ~700

依存:

- bg_cache, kling_cache, atomic_assets
- job_runner.spawn_job

### PR-C: routes/analyze.py (= analyze ジョブ + character_meta + location CRUD)

対象 routes:

- `/api/analyze-jobs` (POST 起動 / GET 一覧 / GET 詳細 / DELETE)
- `/api/character-metas` (GET 一覧 / POST 作成 / PUT / DELETE)
- `/api/locations` (CRUD + preview generation)
- `/api/reference-videos` (= upload / list / delete)

依存:

- analyze.runner, analyze.job, analyze.location, analyze.character_meta

### PR-D: cleanup → app.py

最終 cleanup:

- `preview_server.py` を `app.py` に rename (= 起動 hook + register_blueprint
  のみの薄い entry point)
- 残る `_screenplay_lock` 等の互換 shim を整理
- staged_pipeline 内の循環参照懸念 import を綺麗に
- 既存 tests の `import preview_server` を `import app` か互換 shim で吸収
- LOC 目標: ~150

## 移行原則

各 PR は前 PR を base にせず main から個別に切る。1 Blueprint = 1 PR で
進め、テスト 1233+ 件を全件 pass で維持する。

## 推奨実施順序

1. PR-A (screenplay.py): 最も独立性高い、テスト影響小
2. PR-B (cache.py): bg / kling cache が UI からのみ呼ばれる、影響範囲限定
3. PR-C (analyze.py): analyze 関連は preview_server 内で固まっている
4. PR-D (cleanup): 全 Blueprint が出揃ったら app.py に rename

## ここまでの集大成

8 PR + 計画 doc 2 件で `preview_server.py` の Blueprint 化と `scene_gen.py`
の helper 抽出を完了。残りは:

- preview_server cleanup (= 上記 4 PR)
- scene_gen core 関数抽出 (= 別 doc `2026-05-09_stages-core-extraction.md`)

これらは設計が固まっているので、独立 PR で進められる状態。
