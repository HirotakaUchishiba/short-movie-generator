# コード開発の 24h 自律体制 (superpowers 手法)

最終更新: 2026-05-27
ステータス: ドラフト (dev backlog 実装済み。運用は superpowers 導入 + /goal 起動が前提)

## 1. 背景と目的

動画生成の 24h 自律 (`auto_loop` + `autonomous_runner`) とは別に、**コード開発そのもの**を
24h 自律で進める。開発手法は [obra/superpowers](https://github.com/obra/superpowers)
(Claude Code plugin) の 7 段階を採用する。

### 役割分担 (重要)

| 担い手              | やること                                                                                                                    |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **ユーザー**        | `/plugin install superpowers@claude-plugins-official` (= 手法スキル導入、Claude からは不可) + `/goal` 起動 + Auto Mode 設定 |
| **本実装 (Claude)** | 開発タスクバックログ (`autonomous/dev_backlog.py`) + 24h 開発ループの設計・runbook                                          |

### superpowers 7 段階 (各タスクに適用)

brainstorming → using-git-worktrees → writing-plans → subagent-driven-development →
test-driven-development (red/green/refactor) → requesting-code-review →
finishing-a-development-branch。YAGNI / DRY を重視。

## 2. 設計

### 開発タスクバックログ — `autonomous/dev_backlog.py` [実装済み]

- `data/dev_backlog.jsonl`。`{id, title, detail, priority, status(pending/in_progress/done/failed), branch, pr, error}`。
- `add(title, detail, priority)` / `next_pending()` (priority 昇順 → 作成順) / `mark(id, status, branch, pr, error)` / `list_tasks(status)`。
- タスク源: 人手 `add`、`qa_failures` 集計、`TODO`/`FIXME`、validator 閾値調整候補。

### 24h 開発ループ (/goal + superpowers)

```
/goal: dev_backlog.next_pending() で最優先タスク取得 → mark in_progress
  → [superpowers] brainstorm → worktree → plan → subagent-driven TDD (red/green)
  → requesting-code-review (cross-critique: Claude finder + Codex)
  → finishing-a-development-branch (CI 緑 + review approve で squash マージ)
  → dev_backlog.mark done (branch/pr 記録) → 次のタスク
終了: backlog が空 / budget / turn 上限。
```

### /goal 完了条件の雛形

```
/goal autonomous/dev_backlog.py の next_pending を 1 件取り、superpowers 手法
(brainstorm→plan→TDD→review→finish) で実装し、pytest 全 pass + ruff クリーン +
全体最適レビュー approve を各コマンド出力で示した上で squash マージし mark done せよ。
main 直 push・動画/TTS 再生成・公開はしない。予算 $5 / 30 ターンで停止。
```

## 3. 安全性 (24h 無人マージの前提)

- **品質ゲート**: superpowers の TDD (red/green) + requesting-code-review + CI が「壊れたコードを main に入れない」唯一の砦。完全無制限では branch protection が無いので、これらをすり抜けると壊れたコードが入る (`2026-05-26_verification-automation.md` §3.7-3.8)。
- **盲点対策**: cross-critique は異種 (Codex) が理想だが quota 超過中は Claude finder + 客観検証 (pytest/ruff/CI) に接地する。
- **予算 / 中断**: `/goal --max-budget-usd` / `--max-turns`、`Escape` / `/goal clear`。

## 4. 実装タスク

- [x] `dev_backlog` (add/next_pending/mark/list, priority 順) + 単体テスト
- [ ] superpowers 導入 (= ユーザー操作) + 動作確認
- [ ] 24h 開発ループ runbook (= 本設計書 §2 の完了条件雛形 + superpowers フローに集約)
- [ ] cross-critique の Codex 安定化 (= quota)
- [ ] (任意) `qa_failures` / TODO から dev_backlog へ自動起票するスクリプト

## 5. 現実的制約 (正直な評価)

- `/plugin install` / `/goal` / Auto Mode は **ユーザー操作** (Claude からは起動不可)。
- 真の異種 cross-critique は **Codex quota 依存** (= 本セッション中は超過)。
- 24h 無人マージは **TDD + review + CI の品質ゲートが確実に効くことが大前提**。すり抜けると壊れたコードが main に入る。
- **エージェントの実行安定性**も運用前に要検証 (= 本セッションでツール形式エラーを多発した実績があり、無人運用前に解消が必要)。

## 6. 参考資料

- [obra/superpowers](https://github.com/obra/superpowers) (Claude Code plugin、7 段階開発手法)
- `docs/plannings/2026-05-26_verification-automation.md` (cross-critique / マージゲート / 全体最適レビュー)
- `docs/plannings/2026-05-27_24h-autonomous-operation.md` (動画生成の 24h 自律 = 別系統)
