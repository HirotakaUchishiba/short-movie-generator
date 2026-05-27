# 24 時間自律稼働の設計

最終更新: 2026-05-27
ステータス: ドラフト (Phase 7-8 実装済み)

## 1. 背景と目的

24 時間無人で動画を生成し続ける。主体は Claude セッションでなく **独立 Python プロセス (`auto_loop`)** なので、Claude のコンテキスト肥大とは無関係 (= 各 run は独立プロセス)。

### 既にある基盤 (再評価で判明)

- **予算ガード**: `cost_tracking/budget.py` (daily/monthly cost cap, daily video cap)。`auto_loop._budget_guard`。
- **kill switch**: `auto_loop._kill_switch_guard`。
- **監視通知**: `notify_slack`。
- **自己修正**: validator + retry (`QA_RETRY_LIMITS`)。
- **human gate**: `PRODUCTION_HUMAN_GATE_ENABLED` (= publish 直前で停止)。
- **1 動画実行**: `auto_loop.run_one_video(url, *, license_status, privacy, max_duration, dry_run)`。

### 足りないもの

1. **入力の継続供給**: `auto_loop` は 1 URL → 1 動画。24h には URL キューが要る。
2. **ループオーケストレータ**: キュー消化 (取得 → run_one_video → 次)、1 動画失敗時の継続、予算/kill 停止。
3. **常駐 / 定期起動**: while+sleep or launchd/cron。

### スコープ

やること: URL キュー (Phase 7) + ループランナー (Phase 8)。既存の予算/kill/通知/自己修正を**再利用**する。
やらないこと:

- 予算ガード等の再実装 (= 既にある)。
- 実 24h 稼働の実走 (= 動画生成は API 課金。本設計は dry-run / テストまで、実走は運用者判断)。
- 開発タスク (コード改善) の自律 (= `/goal` + cross-critique。別系統、`2026-05-26_verification-automation.md` 参照)。

## 2. 設計

### URL キュー — `autonomous/task_queue.py` [Phase 7]

- `data/url_queue.jsonl`。1 行 1 ジョブ `{id, url, license, status(pending/done/failed), ts, error, created_at, updated_at}`。
- API: `enqueue(url, license)` / `next_pending()` / `mark(id, status, ts, error)` / `list_jobs(status)`。
- 書き込みは temp + `os.replace` で atomic。

### ループランナー — `scripts/autonomous_runner.py` [Phase 8]

- **責務**: while ループで (1) STOP ファイル / budget cap を確認 → (2) `next_pending` → (3) `run_one_video` → (4) `mark` done/failed → (5) sleep。
- 1 動画の失敗 (`AutoLoopAborted`) は failed 記録で**次へ継続** (= 全体は止めない)。`BudgetExceeded` / STOP ファイル / `--once` / キュー空で終了。
- `run_video` は DI (= テストで auto_loop を呼ばず差し替え可能)。
- 予算ガード・kill switch・通知は auto_loop の既存機構をそのまま使う (= 二重実装しない)。

### 常駐運用 [Phase 9, runbook]

- `launchd`/`cron`、または `while true; do python3 scripts/autonomous_runner.py; sleep 300; done`。
- 安全停止: プロジェクト直下に `AUTONOMOUS_STOP` ファイルを置く。
- 自動上限: `config.DAILY_COST_CAP_USD` / `MONTHLY_COST_CAP_USD` / `DAILY_VIDEO_CAP` (cap=0 は無制限)。
- 開発タスクの自律は `/goal` + cross-critique (別系統)。

## 3. 実装タスク

- [x] Phase 7: `task_queue` (enqueue/next_pending/mark/list) + 単体テスト
- [x] Phase 8: `autonomous_runner` (ループ + 失敗継続 + budget/kill 停止 + DI) + 単体テスト
- [ ] Phase 9: 常駐 runbook + launchd plist 例 + STOP 手順
- [ ] Phase 10: 開発タスク自律の `/goal` 統合 (= verification-automation Phase 4)

## 4. リスクと対策

- **単一ランナー前提**: キューの並行制御は無し (= 複数ランナー同時起動は未対応、将来)。
- **実 24h の課金**: budget cap が唯一の自動歯止め。cap=0 (無制限) のまま放置すると青天井 → 運用前に cap 設定必須。
- **キュー枯渇**: pending が無ければ sleep して待機 (`--once` で 1 周終了)。

## 5. 参考資料

- `scripts/auto_loop.py` (`run_one_video` / `_budget_guard` / `_kill_switch_guard`)
- `cost_tracking/budget.py` (`assert_within_caps` / `BudgetExceeded`)
- `docs/plannings/2026-05-26_verification-automation.md` (開発タスク自律 = 別系統)
