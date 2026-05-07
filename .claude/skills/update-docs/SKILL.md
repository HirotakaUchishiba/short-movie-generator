---
name: update-docs
description: CLAUDE.md やドキュメントを更新・最適化する。「CLAUDE.md を更新して」「ドキュメントを整理して」といった要求で使用。
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# ドキュメント更新スキル

CLAUDE.md / `docs/` 配下のドキュメントを最新の状態に保ち、最適化します。

## 発動条件

以下のような要求で発動:

- 「CLAUDE.md を更新して」「README を最新化して」
- 「ドキュメントを整理して」「ドキュメントを最適化して」
- プロジェクト構造変更後のドキュメント反映

## 対象ドキュメント

### CLAUDE.md

- AI 向けプロジェクト指示書
- 目標行数: 250-350 行
- 詳細は [references/claude-md-guide.md](references/claude-md-guide.md) を参照

### `docs/developments/*.md`

- 静的設計ドキュメント (= ubiquitous-language / architecture / testing / coding-rules / claude-code-usage)
- 末尾の「最終更新」日付を更新する習慣を保つ

### `docs/plannings/*.md`

- フロー文書。日付 prefix `YYYY-MM-DD_*.md`
- 完了済みタスクは打ち消さず `[x]` 化する (= `coding-rules.md` §7)

### その他

- `docs/content-strategy.md` / `architecture-decisions.md` / `abstract-screenplay-design.md`
- `tests/factories/` の docstring

## ワークフロー

### Phase 1: 現状把握

**情報収集:**

1. 対象ドキュメントの読み込み
2. `main.py` のサブコマンドと `scripts/*.py` のエントリ抽出
3. `requirements.txt` / `frontend/package.json` の依存バージョン確認
4. プロジェクト構造の確認 (= `docs/developments/architecture.md` §7 と実態の差分)

### Phase 2: 差分分析

**チェック項目:**

- コマンドの追加・削除・変更
- 依存バージョンの更新
- ディレクトリ構造の変更
- 新機能・削除機能の反映
- ステージ番号 / ドメイン用語の整合性

### Phase 3: 更新実行

**CLAUDE.md 更新時:**

1. 重要ルール (= 段階的ゲート方式) を冒頭に配置
2. よく使うコマンド (= `python3 main.py` / `python3 preview_server.py` / `pytest`) を上位に
3. 冗長な情報を削除
4. ソースコードへの参照を活用 (= `docs/developments/*.md` への link)

**更新後のレポート:**

- 変更前後の行数
- 主要な変更点のサマリー

## CLAUDE.md 構成ガイドライン

### 推奨構成 (上から順に)

1. 最重要ルール (Golden Rules)
2. クイックリファレンス (コマンド)
3. システム概要 (3-5 行)
4. 開発ワークフロー (= 段階的ゲート方式)
5. 詳細仕様 (必要最小限)

### 削除対象

- 詳細な型定義リスト
- 詳細な UI コンポーネントリスト
- 50 行を超える実装例
- 重複情報 (= `docs/developments/*.md` に既出のもの)

## 注意事項

1. **既存構造の尊重**: 大幅な構成変更は確認してから
2. **情報の正確性**: `requirements.txt` / `frontend/package.json` と整合性を取る
3. **簡潔さ**: 詳細はソースコード参照に誘導 (= `docs/developments/*.md`)
4. **日本語**: ドキュメントは日本語で記述
