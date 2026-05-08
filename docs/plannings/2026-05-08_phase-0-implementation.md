# Phase 0 実装記録 (= 計測基盤)

**date**: 2026-05-08 / **PR**: #68 / **branch**: `feat/phase-0-measurement`

`docs/plannings/2026-05-07_full-automation-implementation-plan.md` §2 の Phase 0 出口 KPI に対応する実装。Phase 1 以降の量産経路 / QA / closed-loop が読み取るデータ層を確定する。

## 設計判断 (= 計画書から逸脱した点)

| 計画書原案                                                     | 実装                                                 | 理由                                                                                                                                                                          |
| -------------------------------------------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `generation_records.video_id` を PRIMARY KEY                   | **`ts` を PK / `video_id` は nullable + REFERENCES** | `videos.id` は `ingest_video.py` 完了後に決まる。stage 実行時点では未確定なので、ts ベースで append できる構造に変えた。video_id は Phase 1 の publish 完了で backfill 想定。 |
| `qa_failures.tags JSON NOT NULL`                               | `TEXT NOT NULL DEFAULT '[]'`                         | SQLite には JSON 型が無いため。`json.loads` で deserialize。空 list 許容 (= regenerate_implicit はタグ無し)。                                                                 |
| reject 後に承認をリセットするか?                               | **触らない**                                         | データ収集専用。再生成したい場合は別途 `/regen` を叩く。承認リセットは設計原則「指示の範囲を超えない」と整合。                                                                |
| `analytics/schema.sql` の `ALTER TABLE` を別ファイル migration | **既存の `_ensure_column` 経路に乗せる**             | `analytics/db.py` に既に `final_*` カラム追加の前例あり。同じパターンで reference_videos 拡張を additive migration。                                                          |
| `scripts/migrate.py` で sqlalchemy alembic 等を導入            | **`init_db()` を呼ぶだけのシン**                     | `_ensure_column` で十分 idempotent。alembic は overkill。                                                                                                                     |

## 実装した契約

### `generation_records.stage_runs` (= JSON list of stage runs)

```json
[
  {"stage": "script", "started_at": "...", "ended_at": "...", "status": "completed", "retry_count": 0, "cost_usd": null},
  {"stage": "tts", ..., "status": "failed", "error": "timeout"}
]
```

- `staged_pipeline.run_next_stage` が成功 / 失敗の両方で append
- analytics DB 障害は `logger.warning` で握りつぶし、pipeline を止めない
- `cost_usd` は Phase 0 では常に `None`。Phase 1 の auto_loop で cost_records.jsonl と相関させて埋める想定
- `retry_count` は Phase 0 では常に 0。Phase 2 の retry hook で増える

### `generation_records.status` (= top-level)

`in_progress` (default) → `completed` / `auto_rejected` / `failed`。Phase 0 では `in_progress` のまま。最終 stage 完了時に `update_generation_record(ts, status="completed")` で閉じる責務は Phase 1 の auto_loop が持つ。

### `qa_failures.source`

`human_reject` / `auto_flagged` / `regenerate_implicit` / `post_publish_lowperf`。Phase 0 では前 2 つのみ書き込まれる:

- `human_reject`: UI の "✗ NG 記録" ボタン
- `regenerate_implicit`: `/regen` 経由の再生成直前。tags は空 list

### `reference_videos.license_status`

`unconfirmed` (default) / `user_owned` / `fair_use_review` / `public_domain`。Phase 1 の `scripts/fetch_reference.py` で必須項目になり、`unconfirmed` は analyze pipeline に進めない gate になる予定。

### `DISABLE_AUTO_LOOP=1` の挙動

`main.py` 冒頭で `sys.exit(2)`。手動運用 (= env 未設定) では従来通り動く。Phase 1 の cron が叩く `auto_loop.py` も同じ env を尊重する想定。

## 出口 KPI チェック (= Phase 0 → 1 への gate)

> Phase 0 出口 KPI: 不良サンプル ≥ 10 件 / 正常サンプル ≥ 10 件 / `generation_records` スキーマ確定 / 全 stage で seed・prompt・retry が残る

| 項目                              | 状態                                                                                                                                           |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `generation_records` スキーマ確定 | ✅ schema v5 として確定。stage_runs / prompts / seeds / api_meta / validator_scores の JSON フィールドを用意                                   |
| 全 stage の record 経路           | ✅ `staged_pipeline.run_next_stage` が hook (success / fail 両方)                                                                              |
| reject 経路                       | ✅ `/api/projects/<TS>/reject` (UI ボタンから)                                                                                                 |
| regenerate 自動アーカイブ         | ✅ `_archive_before_regen`                                                                                                                     |
| 不良 ≥ 10 + 正常 ≥ 10             | ⏳ **手動運用継続でユーザ側が達成する**。`scripts/dashboard.py` (Streamlit) に Phase 進捗パネルを足すのは Phase 1 で実装予定                   |
| seed の記録                       | ⚠️ Phase 0 ではフィールドを用意しただけ。Imagen / Kling の seed を `update_generation_record(ts, seeds=...)` で書き込むのは Phase 1 で組み込む |
| prompt の記録                     | ⚠️ 同上。`prompts` フィールドへの書き込みは Phase 1 で auto_loop / scene_gen に組み込む                                                        |

つまり **コードの計測基盤は揃った** が、実データ蓄積 (= 不良 / 正常サンプル) と prompts/seeds の自動書き込みは Phase 1 と並行で進める。Phase 1 の `auto_loop.py` 実装時に以下を追加する:

- 各 stage 開始時に `update_generation_record(ts, prompts=...)` で生成 prompt を保存
- Imagen / Kling の seed が API レスポンスに乗るので、それも同時に保存
- publish 完了で `status="completed"`、auto_rejected で `status="auto_rejected"`

## Phase 1 着手時の TODO

- `scripts/fetch_reference.py` で `reference_videos.source_url / fetched_at / license_status` 必須化
- `scripts/auto_loop.py` で kill-switch / cost guard / Slack / unlisted 強制
- `auto_loop.py` から `update_generation_record(ts, prompts=..., seeds=...)` を呼んで Phase 0 のフィールドを実データで埋める
- `qa/validators_provisional.py` (= silence/clip 検査) で `qa_failures` に `source="auto_flagged"` を書き込む

## 残課題 / 後続 Phase での補強

- frontend `qaCategories.ts` と backend `qa/categories.py` の手動同期は将来 `/api/config` 経由で取得する形に統一すべき (Phase 2 で validator が増えるとここの drift が顕在化する)
- `_stage_artifact_paths` は stage / scene_idx / line_idx の組み合わせで artifact を返す素朴な mapping。シーン番号が複数 segment にまたがる Phase 2 の retry hook で同じ mapping を共用する想定
