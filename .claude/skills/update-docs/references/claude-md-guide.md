# CLAUDE.md 最適化ガイド

## 目的

CLAUDE.md は、Claude Code がプロジェクトを effective に理解するための指示書です。

## 目標

- **行数**: 250-350 行
- **構造**: AI 処理に最適化
- **情報**: 最新かつ正確

## 推奨構成

### 1. 最重要ルール (Golden Rules)

```markdown
## 🔴 最重要ルール (Golden Rules)

### 基本原則

- 要求されたことのみを実行する
- 必要な作業は提案し確認を得る
- 会話は日本語、コミットメッセージは英語

### コード品質

- 実装完了時は `pytest` を実行
- 型エラー / lint エラーは必ず修正 (= `ruff check`)
- 規約は `docs/developments/coding-rules.md` を参照
```

### 2. クイックリファレンス

```markdown
## 📋 クイックリファレンス

### 開発コマンド

\`\`\`bash
python3 main.py <台本> # 1 stage 実行
python3 main.py <台本> --resume <TS> # 次 stage 実行
python3 preview_server.py # バックエンド (http://127.0.0.1:5555)
cd frontend && npm run dev # フロント開発サーバ
pytest # 全テスト
ruff format . && ruff check --fix . # 整形 + 修正
\`\`\`
```

### 3. システム概要 (簡潔に)

```markdown
## 🏗️ システム概要

**tensyoku_movie_generator** — 転職系ショート動画を自動生成する日本語特化ツール

- 入力: `screenplays/<名前>.json` (= 手書き台本 or analyze 経由の自動生成)
- 出力: 9:16 縦長動画 + SNS キャプション
- フロー: 段階的ゲート方式 (= 1 起動 = 1 stage、UI 承認で次へ)
```

### 4. 開発ワークフロー

- 段階的ゲート方式 (8 stage) の説明
- テスト規約 (= `docs/developments/testing.md` への参照)
- コミット規約 (= 英語、`feat`/`fix`/`docs`/`refactor`/`chore`/`test`)

### 5. 詳細仕様 (必要最小限)

- ドメイン固有の重要概念のみ
- 詳細はソースコード参照へ誘導 (= `docs/developments/*.md`)

## 削除すべき情報

### 詳細すぎる情報

- 全ての型定義の列挙
- 全てのコンポーネントの列挙
- 50 行を超えるコード例

### 重複情報

- `requirements.txt` / `package.json` と同じ内容
- README と同じ内容
- ソースコードのコメントと同じ内容
- `docs/developments/coding-rules.md` 等と完全重複する規約

### 古い情報

- 削除された機能の説明
- 変更されたコマンド
- 9-stage 表記など更新前の用語

## 更新チェックリスト

### 定期更新項目

- [ ] `requirements.txt` の追加・削除
- [ ] `frontend/package.json` の依存バージョン
- [ ] ディレクトリ構造の変更
- [ ] 新機能・削除機能
- [ ] Stage 番号 / プロバイダ追加の反映

### 更新時の確認

- [ ] 行数が目標範囲内 (250-350 行)
- [ ] 最重要ルールが冒頭にある
- [ ] コマンドが最新
- [ ] 重複がない (= `docs/developments/*.md` への委譲)
- [ ] ドメイン用語が `ubiquitous-language.md` と一致

## 更新レポート形式

```markdown
## CLAUDE.md 更新レポート

### 行数

- 更新前: XXX 行
- 更新後: XXX 行

### 主要な変更点

1. [変更 1]
2. [変更 2]
3. [変更 3]

### 削除した情報

- [削除 1]
- [削除 2]

### 追加した情報

- [追加 1]
- [追加 2]
```
