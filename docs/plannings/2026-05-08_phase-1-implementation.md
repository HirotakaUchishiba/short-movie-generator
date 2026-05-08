# Phase 1 実装記録 (= Open-loop 量産経路)

**date**: 2026-05-08 / **PR**: #69 / **branch**: `feat/phase-1-openloop`

`docs/plannings/2026-05-07_full-automation-implementation-plan.md` §3 の Phase 1 出口 KPI に対応する実装。Phase 0 の計測基盤の上に「URL → unlisted YouTube 公開」を 1 コマンド化する。

## 設計判断 (= 計画書原案からの逸脱)

| 計画書原案                                                   | 実装                                                              | 理由                                                                                                                                                                                                            |
| ------------------------------------------------------------ | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| auto_loop は preview_server に `requests` で REST を叩く     | **`staged_pipeline` を直接 import**                               | cron 実行で preview_server を別プロセスで稼働させる前提は重い。SQLite は concurrent write OK。reject UI 等の preview 機能と auto_loop は独立に動かせる構造を維持。                                              |
| stage 全体の retry を 1 stage = 1 ジョブで再実行             | **`staged_pipeline.regen(stage, scene_idx=None)` を呼んで上書き** | regen は既に `qa/artifact_paths.stage_artifact_paths` で artifact 解決済み + auto_loop 側で `regenerate_implicit` archive を仕掛けるので、再生成 + 暗黙アーカイブが両立。                                       |
| validator NG = stage を retry                                | **stage 全体 (= 全シーン) を regen で上書き**                     | シーン単位 retry のほうがコスト効率良い (Kling 1 シーン $0.6) が、Phase 1 の暫定 validator はファイル単位の判定なので「どのシーンが NG か」を返さない。Phase 2 の多軸 validator でシーン単位 retry を導入する。 |
| YouTube `privacy` を `final_import.publish` の引数だけで制御 | **`platform_clients/youtube._resolve_privacy` で二重防衛**        | auto_loop 経由でも CLI 直叩き (`python3 main.py --publish youtube --privacy public`) でも `AUTO_LOOP_ALLOW_PUBLIC=0` 中は `unlisted` に降格。env 1 つで Phase 4 までの公開先制限を一元管理。                    |

## 公約と契約

### orchestrator の責務境界 (`scripts/auto_loop.py`)

```
run_one_video(url, license_status, privacy, max_duration, dry_run) -> ts

  1. license gate            (= VALID_LICENSES のみ)
  2. _kill_switch_guard      (= DISABLE_AUTO_LOOP=1 で SystemExit)
  3. _budget_guard           (= cost / video cap で BudgetExceeded)
  4. fetch_reference         (= yt-dlp + reference_videos 登録)
  5. analyze.run             (= Claude で screenplays/auto_<sha>.json)
  6. run_script              (= temp/<TS>/ 作成 + snapshot)
  7. for stage in (tts, bg, kling, scene, overlay):
       run_next_stage  →  validator  →  retry (1) if NG  →  approve
  8. import_final            (= reels_<TS>.mp4 を canonical 化)
  9. publish (youtube)       (= AUTO_LOOP_ALLOW_PUBLIC=0 で unlisted 強制)
```

各 step での失敗は:

- `kill_switch` / `budget` → 例外 raise (= caller が exit)
- `fetch` / `analyze` → `notify_slack("error")` + `AutoLoopAborted` raise
- stage `validator` 1 回 retry → 2 回目も NG なら `notify_slack("error")` + `AutoLoopAborted`
- 例外時は `generation_records.status = "auto_rejected"`、成功時は `"completed"`

### Cost / Video Cap の評価単位

`cost_tracking.budget`:

- daily cost: `cost_records.jsonl` の `timestamp >= 今日 0:00 UTC` の合計
- monthly cost: 同上、月初 0:00 UTC から
- daily video count: `generation_records.created_at >= 今日 0:00 UTC` の行数

`cap = 0` は無制限 (= dev / test で gate を無効化する用)。
DB / jsonl 障害は warn + 0 にして auto_loop を通す (= cap 判定不能でも pipeline は走らせる)。

### 暫定 validator (Phase 2 で再 baseline)

| validator                 | 入力          | fail 条件                                           | しきい値の根拠                                                                   |
| ------------------------- | ------------- | --------------------------------------------------- | -------------------------------------------------------------------------------- |
| `check_tts_audio`         | `tts_*_*.mp3` | `mean_volume_db < -45` または `silence_ratio > 0.5` | 保守的初期値。Phase 2 の `eval_validators.py` で qa_failures 実例から再 baseline |
| `check_kling_blackframes` | `kling_*.mp4` | `black_ratio > 0.5`                                 | 同上                                                                             |

これらが auto_flagged で `qa_failures` に書き込み、retry が `regenerate_implicit` で旧世代を archive する。Phase 2 が両方を読んで多軸 validator のしきい値学習に使う。

### YouTube 公開先強制 (二重防衛)

1. `auto_loop` 経由: 引数 `privacy="unlisted"` を渡す (= デフォルト)
2. `platform_clients.youtube.upload_video`: `_resolve_privacy("public")` が `AUTO_LOOP_ALLOW_PUBLIC=0` の間 `"unlisted"` に降格

CLI 直叩き (`python3 main.py --publish youtube --privacy public`) でも 2 で gate されるので、env を切り替えるまで本番アカウント公開は起こらない。Phase 4 の本番展開時に `AUTO_LOOP_ALLOW_PUBLIC=1` にする。

## 出口 KPI チェック

> Phase 1 出口 KPI: 7 日連続で 1 日 3 本の cron が成功 (= 21/21 が publish 到達) / 公開先 unlisted / 失敗時 Slack 通知

| 項目                    | 状態                                                                                                                                        |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 コマンドで 1 動画完走 | ✅ `python3 scripts/auto_loop.py <URL> --license user_owned`                                                                                |
| cron 起動               | ⏳ ユーザ環境の `crontab` 設定で実現 (= 例: `0 9,15,21 * * * cd /path && /usr/bin/python3 scripts/auto_loop.py <URL> --license user_owned`) |
| 公開先 unlisted         | ✅ `AUTO_LOOP_ALLOW_PUBLIC=0` (default) で強制                                                                                              |
| Slack 通知              | ✅ `SLACK_WEBHOOK_URL` 設定で発火                                                                                                           |
| cost guard              | ✅ `DAILY_COST_CAP_USD=20` / `MONTHLY_COST_CAP_USD=300`                                                                                     |
| video count cap         | ✅ `DAILY_VIDEO_CAP=5`                                                                                                                      |
| 7 日連続 21/21          | ⏳ **実運用検証**。 ユーザ側で実機 cron を回して達成。失敗時の挙動は `qa_failures` (auto_flagged) と Slack に残る                           |

## Phase 2 着手時の TODO

- `qa/validators/` 配下に 7 軸 validator (`audio_silence` / `audio_clipping` / `subtitle_overlap` / `character_drift` / `lipsync_quality` / `subtitle_readability` / `story_pacing`)
- 各 validator はシーン単位の `(scene_idx, line_idx, score, reason)` を返し、auto_loop が「このシーンだけ regen」できる粒度に
- `qa/eval_validators.py` を週次で回し、Phase 1 で蓄積された `qa_failures` の `auto_flagged` + `human_reject` を入力に recall / precision を出す
- `cost_records.jsonl` に Phase 0 で追加した `prompts` / `seeds` も auto_loop が `update_generation_record(ts, prompts=..., seeds=...)` で書き込む

## 残課題

- analyze の cost が `cost_records.jsonl` に記録されているが `generation_records.total_cost_usd` には反映されていない (= `staged_pipeline._record_stage_run` が `cost_usd=None` で append しているため)。Phase 2 で `cost_tracking` から該当 stage の record を逆引きして埋める想定
- auto_loop 内で `update_generation_record(ts, prompts=...)` を呼ぶ箇所が無い (= scene_gen / TTS の prompt が DB に残らない)。Phase 2 の closed-loop 検証で必要になるため、stage 完了時に prompts を集める hook を追加する
- `fetch_reference.py` の `--max-duration` が yt-dlp の `--match-filter "duration <= N"` に翻訳されるが、URL によっては duration メタが取れない。フォールバックとして DL 後の ffprobe チェックを入れるかは Phase 2 の課題

## レビュー対応 (2026-05-08, post-PR #69 review)

PR レビューで挙がった 8 件の改善を 1 commit にまとめて修正:

| #   | 内容                                                                                                                                                                                                    | 修正箇所                                                                                                                                                      |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `qa/artifact_paths.py` が **unpadded 命名** (`bg_0.png`) を使っており、production の `bg_{idx:03d}.png` にマッチしていなかった。reject + auto_loop の per-scene archive がそもそも全経路で no-op だった | `qa/artifact_paths.py` を 3 桁ゼロ詰め + `scene_idx=None` で全シーン glob。tests も実 production 命名に揃える + auto_loop の per-scene archive 回帰テスト追加 |
| 2   | `cost_tracking/budget._count_videos_since` が `strftime("%Y-%m-%d %H:%M:%S")` で query しており、実 stored `_now()` (= ISO + tz) と format mismatch                                                     | `since.isoformat(timespec="seconds")` に変更。今日 / 昨日が混ざらないことを契約テストで固定                                                                   |
| 3   | `_resolve_privacy("Public")` (mixed case) が降格判定をくぐり抜けていた                                                                                                                                  | `.strip().lower()` で正規化 + casing バリエーションのテスト 3 本追加                                                                                          |
| 4   | `analytics.db.append_stage_run` の SELECT-then-UPDATE が並列 worker で lost update する可能性 (= 既に `BEGIN IMMEDIATE` 修正は ed7b0f2 で入っていたが、回帰テストが無かった)                            | `tests/test_analytics_db.py::test_append_stage_run_concurrent_no_lost_entries` 追加                                                                           |
| 5   | `preview_server._stage_cache_delete` の `not is_deleted` 経路 (404) のテストが無く、`deleted` 未定義バグ (e039778 で修正済) の回帰検出ができていなかった                                                | `tests/test_preview_server_kling_cache.py::test_cache_delete_returns_404_when_entry_missing` 追加                                                             |
| 6   | `fetch_with_ytdlp` の tmp leak (yt-dlp 失敗時の cleanup pattern が脆い) と container fallback (best が webm を返した時に `.mp4` 拡張子のまま webm 中身)                                                 | `try/finally` で leak 完全防止 + `--merge-output-format mp4` で container 強制。tests 3 本追加                                                                |
| 7   | `AUTO_LOOP_STAGE_TIMEOUT_SEC` が "TIMEOUT" を名乗りながら soft warning だった                                                                                                                           | `AUTO_LOOP_STAGE_SOFT_LIMIT_SEC` にリネーム + コメントで「hard 中断ではない」明記                                                                             |
| 8   | auto_loop の `_import_raw_as_final` が将来 fingerprint hard fail 化された時の invariants が未文書化                                                                                                     | docstring に "raw === raw で score=1.0 になるので gate 通過" の根拠を明記                                                                                     |

### 設計判断

- Issue #1 は当初「auto_loop の retry archive で scene_idx=None だと bg/kling/scene が空 list を返す」という小バグだと診断したが、調査の過程で **製品コード全体の命名規約** (= `{idx:03d}`) と `qa/artifact_paths.py` (= unpadded) の **format mismatch** が真因だと判明。Phase 0 の reject API も含め、per-scene の artifact archive は **PR 全体で常に no-op** になっていた。`stage_artifact_paths` を SSOT としてゼロ詰め + glob 双方をサポートする形に統一し、reject UI / auto_loop / regenerate 全経路を同時に回復させた
- Issue #4 は ed7b0f2 で既に `BEGIN IMMEDIATE` が入っていたが、`update_generation_record` 側にしか並列テストが無かった。同じ防御を `append_stage_run` にも回帰テストとして固定し、Phase 2 で並列 worker を入れる時に bound として残す
- Issue #6 の `--merge-output-format mp4` は yt-dlp が ffmpeg を呼ぶ前提の機能。本プロジェクトは Phase 1 で qa/validators_provisional が既に ffmpeg 必須なので、追加依存は無い
