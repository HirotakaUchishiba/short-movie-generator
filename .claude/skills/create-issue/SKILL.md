---
name: create-issue
description: GitHub issue を作成する。「issue を作って」「バグを報告して」「機能リクエストを登録して」「この問題を issue にして」といった要求で使用。コンテキストを自動検出し、適切なラベルとフォーマットで issue を作成。
allowed-tools: Read, Glob, Grep, Bash
---

# GitHub Issue 作成スキル

コンテキストを自動検出し、適切なフォーマットとラベルで GitHub issue を作成します。

## 発動条件

以下のような要求で発動:

- 「issue を作って」「バグを報告して」
- 「機能リクエストを登録して」「この問題を issue にして」
- エラー発生後の「これを issue にして」

## ワークフロー

### Phase 1: コンテキスト検出

**自動検出項目:**

- 現在開いているファイル
- 最近のエラーメッセージ (= log / pytest 失敗 / `temp/<TS>/` の異常)
- 現在のディレクトリ / モジュール
- 関連するコードスニペット

**issue タイプの判定:**

| タイプ        | 判定基準                         |
| ------------- | -------------------------------- |
| Bug           | エラー、不具合、期待と異なる動作 |
| Enhancement   | 新機能、改善、機能追加           |
| Refactoring   | コード改善、技術的負債           |
| Documentation | ドキュメント更新、追加           |

### Phase 2: 内容生成

**必須フィールド:**

- タイトル: 明確で行動可能な形式
- 優先度ラベル: 🔴 High / 🟡 Medium / 🟢 Low
- 説明: 詳細な説明

**Bug の場合の追加項目:**

- 再現手順 (= 台本名、stage、provider 等)
- 期待される動作
- 実際の動作
- 環境情報 (= Python / ffmpeg / OS / 関連 API モデル)

### Phase 3: Issue 作成

`gh issue create` コマンドを使用。

詳細なテンプレートは [references/issue-templates.md](references/issue-templates.md) を参照。

## ラベル選択基準

### 優先度 (必須)

| ラベル    | 基準                                                     |
| --------- | -------------------------------------------------------- |
| 🔴 High   | 重要機能が壊れている、開発がブロックされる、API 課金事故 |
| 🟡 Medium | 重要な改善、非クリティカルなバグ                         |
| 🟢 Low    | あると良い改善、技術的負債                               |

### スコープ (該当する場合)

- `scope:pipeline` — Stage 1〜6 の生成パイプライン (= TTS / bg / kling / scene / overlay)
- `scope:final-import` — Stage 7 取込 (= watchdog / fingerprint / final_import)
- `scope:publish` — Stage 8 公開 (= YouTube / IG / TikTok)
- `scope:analytics` — analytics DB / metrics / dashboard
- `scope:analyze` — analyze pipeline (= 参考動画 → 抽象台本)
- `scope:frontend` — preview UI (React + Vite)
- `scope:infra` — config / env / `.claude/settings.json` 等の運用

## 出力

作成後、issue の URL をユーザーに報告します。

## 使用例

```
ユーザー: Stage 4 Kling で 429 が出続けるので issue を作って
→ ラベル: 🟡 Medium, scope:pipeline

ユーザー: YouTube quota 403 のハンドリングを足したい
→ ラベル: 🟢 Low, scope:publish

ユーザー: preview UI の Stage 6 で字幕タイミングが崩れる、本番影響あり
→ ラベル: 🔴 High, scope:frontend
```
