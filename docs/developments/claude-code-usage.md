# Claude Code 運用

本ドキュメントは short_movie_generator 内で Claude Code を使う際の **設定 (`.claude/`) / hooks / commands / skill / plugins** の現状と推奨を集約する。

---

## 1. 目的

- 単独開発でも Claude Code を「常時隣にいるレビュアー + 実装補助」として使う
- 本プロジェクトの規約 (= `coding-rules.md` / `architecture.md` / `testing.md`) を Claude が自動で踏襲する
- 操作の摩擦 (= 許可プロンプト連打 / フォーマット手動修正 / 規約逸脱の見逃し) を減らす

---

## 2. 現状の `.claude/` 構成

```
.claude/
  settings.local.json    ← 個人 / マシン依存の許可設定 (git ignore 対象 推奨)
  worktrees/             ← Claude Code が isolation 用に切る git worktree 置き場
```

`.claude/settings.json` (= プロジェクト共通設定) は**未作成**。チーム規模ではないため当面は `settings.local.json` のみで運用しているが、共通化したい設定 (= hooks / 共有コマンド許可) が増えたら新設する。

### `settings.local.json` の現在の中身 (= 抜粋)

```json
{
  "permissions": {
    "allow": [
      "Skill(update-config)",
      "Read(//private/tmp/**)",
      "Bash(python3 -m pytest tests/test_bg_cache.py)"
    ]
  }
}
```

頻繁に許可プロンプトが出るコマンドは `/fewer-permission-prompts` skill で transcript からスキャンしてここに追加する運用。

---

## 3. 推奨する hooks

`PostToolUse` で **Edit / Write が走った後に linter / formatter を自動実行** すると、Claude が書いたコードが規約から逸脱する確率を大幅に下げられる。

### 3.1 Python コード保存後の `ruff` 自動実行

`.claude/settings.json` (新設) に下記を追加する想定:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "if echo \"$CLAUDE_FILE_PATH\" | grep -qE '\\.py$'; then ruff format \"$CLAUDE_FILE_PATH\" && ruff check --fix \"$CLAUDE_FILE_PATH\"; fi"
          }
        ]
      }
    ]
  }
}
```

- `ruff format` で整形 → `ruff check --fix` で safe-fix を反映
- 失敗時はその場で気付ける (= Claude にフィードバックが返る)
- 設定変更は `/update-config` skill で行う

### 3.2 frontend コード保存後の `prettier`

```json
{
  "type": "command",
  "command": "if echo \"$CLAUDE_FILE_PATH\" | grep -qE '\\.(ts|tsx|js|jsx|css|json|md)$'; then (cd frontend && npx --no-install prettier --write \"$CLAUDE_FILE_PATH\" 2>/dev/null) || true; fi"
}
```

`frontend/` 配下に絞って prettier を当てる。`(cd ... && ...) || true` で frontend 外の md/json 編集が壊さないようにフォールバック。

### 3.3 SessionStart で本ドキュメントを通知

`SessionStart` hook で「`docs/developments/` を読むこと」を Claude に再認識させる:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo 'See docs/developments/ for architecture / testing / coding-rules / ubiquitous-language / claude-code-usage.'"
          }
        ]
      }
    ]
  }
}
```

---

## 4. 推奨する commands / skill

### 4.0 プロジェクト固有スキル / プラグイン

trass 由来の skill / command / plugin を本プロジェクトに移植済み。発動条件は以下:

| 発話例 / 入力                                      | 発動するスキル・コマンド   | 配置                                                                |
| -------------------------------------------------- | -------------------------- | ------------------------------------------------------------------- |
| 「設計書を書いて」                                 | design-document スキル     | `.claude/skills/design-document/`                                   |
| 「リファクタしたい」「コード品質を改善したい」     | analyze-refactoring スキル | `.claude/skills/analyze-refactoring/`                               |
| 「CLAUDE.md を更新して」「ドキュメントを整理して」 | update-docs スキル         | `.claude/skills/update-docs/`                                       |
| 「issue を作って」「バグを報告して」               | create-issue スキル        | `.claude/skills/create-issue/`                                      |
| `/commit-push`                                     | commit-push コマンド       | `.claude/commands/commit-push.md`                                   |
| `/generate-testcases <feature>`                    | generate-testcases plugin  | `.claude/plugins/generate-testcases/commands/generate-testcases.md` |

詳細は各 SKILL.md / コマンド md を参照。

### 4.1 PR / コードレビュー

| コマンド            | 用途                                                                   |
| ------------------- | ---------------------------------------------------------------------- |
| `/review`           | 現在のブランチの差分を Claude に厳しめにレビューさせる (= self-review) |
| `/security-review`  | 同差分を security 観点で見る (= 機密情報の log 流出 / 公開先誤りなど)  |
| `/ultrareview <PR>` | PR を multi-agent でレビューさせる (= 大型変更時のみ。billed)          |
| `/simplify`         | 直近の差分から「簡素化できる箇所」を Claude に拾わせる                 |

`/review` を **PR を出す前に必ず 1 回回す** 運用が単独開発の品質を底上げする。

### 4.2 設定 / 初期化系

| コマンド                    | 用途                                                          |
| --------------------------- | ------------------------------------------------------------- |
| `/update-config`            | `.claude/settings.json` の編集 (= hooks / 許可リスト追加)     |
| `/fewer-permission-prompts` | transcript から頻出 read-only コマンドを抽出して allowlist 化 |
| `/init`                     | CLAUDE.md の生成・更新                                        |

### 4.3 自動化

| コマンド                    | 用途                                                                                       |
| --------------------------- | ------------------------------------------------------------------------------------------ |
| `/loop <interval> <cmd>`    | 定期的に同じ slash command を走らせる (例: Stage 4 Kling の polling 監視 / `/babysit-prs`) |
| `/loop <cmd>` (no interval) | model 自身が pacing する。長尺ジョブ完了監視に                                             |
| `/schedule`                 | cron 化された routine を作成・管理                                                         |

`/loop` の例 (= 後述 §6)。

### 4.4 ドキュメント / メモリ

| コマンド    | 用途                                             |
| ----------- | ------------------------------------------------ |
| `/remember` | 次回以降のセッションに残したい情報をメモリに保存 |

---

## 5. PR レビューの運用

単独開発でもセルフレビューを儀式化する。

```
1. ブランチで実装 → コミット
2. `gh pr create` で PR を作る
3. ターミナルで `/review` を実行 (= ローカルブランチに対して)
4. 指摘点を確認し、必要なら修正してコミット追加
5. PR をマージ
```

**Phase B 以降の大規模 refactor 時は `/ultrareview <PR>`** を使う (= multi-agent で複数視点)。billed なので使い所を選ぶ。

---

## 6. `/loop` の使い所 (本プロジェクト固有)

| シナリオ                                                      | コマンド例                                              |
| ------------------------------------------------------------- | ------------------------------------------------------- |
| Stage 4 Kling の長時間 polling を model に babysitting させる | `/loop /poll-kling-status <ts>` (custom skill 化が前提) |
| Phase 1 で auto_loop.py の cron 動作を model にチェックさせる | `/loop 30m /check-auto-loop`                            |
| metrics fetch の連日チェック                                  | `/loop 1d /fetch-metrics-and-summarize`                 |
| 長大な refactor タスクの段階的進行                            | `/loop /next-refactor-step` (= autonomous mode)         |

`/loop` 起動中は対話のたびに同じ task が再実行される。**意図せず long-run になる**ので、必ず観測可能な状態 (= log や Slack 通知) と組み合わせる。

---

## 7. plugins 選定方針

| plugin              | 採用方針                                                                                        |
| ------------------- | ----------------------------------------------------------------------------------------------- |
| `code-review`       | 推奨 (= `/review` で常用)                                                                       |
| `pr-review-toolkit` | 推奨 (= `/ultrareview` 等)                                                                      |
| `feature-dev`       | 中規模機能の段階分割に有用。Phase 0-3 のいずれかで導入検討                                      |
| `claude-code-guide` | 任意 (= Claude Code 自体の使い方相談時のみ)                                                     |
| 業務固有 plugin     | short_movie_generator 用カスタム plugin は **必要が出てから** 追加。今は標準 + 追加 1〜2 で十分 |

---

## 8. 安全装置

| 装置                                   | 設定                                                                                |
| -------------------------------------- | ----------------------------------------------------------------------------------- |
| destructive コマンドの自動実行禁止     | `git push --force` / `git reset --hard` / `rm -rf` は許可リストに**入れない**       |
| 本番アカウントへの publish の二重 gate | (Phase 4) `AUTO_LOOP_ALLOW_PUBLIC=0` を default、env で明示しない限り本番公開を禁止 |
| 隔離実行                               | 大きな実装タスクは `Agent({isolation: "worktree"})` で worktree 切って試行          |
| commit / PR / push の実行              | ユーザの明示確認後のみ。CLAUDE.md 「Executing actions with care」の方針             |

---

## 9. 落とし穴

| 落とし穴                                                    | 対処                                                                             |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `.claude/settings.local.json` を git に commit してしまう   | `.gitignore` に追加 (= 個人マシン依存)                                           |
| ruff format hook で意図せず大量行が変わる                   | 初回は手動で `ruff format .` を一括適用してから hook を導入する                  |
| `/loop` で API コストが膨らむ                               | interval を短くしすぎない。1 サイクル分のコストを意識する                        |
| 許可リストに広いパターン (= `Bash(*)`) を入れる             | 一見便利だが信用毀損の元。`Bash(python3 -m pytest *)` のように動詞単位で許可する |
| Claude が docs/developments/ を無視して暗黙ルールを発明する | SessionStart hook (§3.3) で読む癖をつける + CLAUDE.md にも明示参照を残す         |

---

## 10. 関連ドキュメント

- `CLAUDE.md` — プロジェクト全体の前提と段階的ゲート方式
- `docs/developments/coding-rules.md` — Claude が踏襲すべき規約
- `docs/developments/architecture.md` — レイヤと依存方向
- `docs/developments/testing.md` — テスト規約
- `docs/developments/ubiquitous-language.md` — ドメイン用語

---

最終更新: 2026-05-07
