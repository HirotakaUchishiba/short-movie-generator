---
name: analyze-refactoring
description: 「問題発見」に特化。コードベース全体を網羅的に調査し、何を直すべきかを優先度付きでリストアップする。「リファクタリングしたい」「コード品質を改善したい」「技術的負債を解消したい」といった要求で使用。
allowed-tools: Read, Write, Glob, Grep, Bash, Task
---

# リファクタリング分析スキル

コードベース全体を網羅的に調査し、包括的なリファクタリング計画を立案します。

## 発動条件

以下のような要求で発動:

- 「リファクタリングしたい」「コードを整理したい」
- 「技術的負債を解消したい」「コード品質を改善したい」
- 定期的なコード品質チェック

## 分析観点

詳細なチェックリストは [references/checklist.md](references/checklist.md) を参照。

### 優先度: Critical

- セキュリティ脆弱性 (XSS / インジェクション / 機密ハードコード)
- 重大なバグの可能性
- データ整合性の問題

### 優先度: High

- 重複コード
- 責務分離の問題
- 型安全性の欠如 (= `Any` 型の多用、`cast` 強制)
- 8-stage パイプラインのレイヤ依存違反 (`docs/developments/architecture.md` §2)

### 優先度: Medium

- パフォーマンス問題
- ガイドライン違反 (`docs/developments/coding-rules.md`)
- 過度な複雑性 (= 50 行超関数 / 3 層超ネスト)

### 優先度: Low

- コードスタイルの不統一
- コメントの過不足
- 軽微な最適化

## ワークフロー

### Phase 1: 網羅的調査

**調査対象:**

- パイプライン中核モジュール: `staged_pipeline.py` / `scene_gen.py` / `compositor.py` / `preview_server.py`
- 外部 API クライアント: `*_client.py` (= elevenlabs / imagen / fal_video / lipsync / whisper / video_analyzer)
- サブパッケージ: `analyze/` / `analytics/` / `final_import/` / `platform_clients/` / `cost_tracking/`
- 補助 CLI: `scripts/*.py`
- frontend: `frontend/src/`
- 主要なファイル (= 500 行以上のファイルを優先)

**調査方法:**

1. Glob / Grep で問題パターンを検索
2. ファイルサイズ・複雑性の確認 (= `wc -l`)
3. 依存関係の分析 (= `import` の方向)

### Phase 2: 問題の分類と優先度付け

**分類基準:**

- 影響範囲 (広い → 高優先)
- 修正リスク (低い → 高優先)
- ビジネス影響 (= 動画生成パイプラインの停止リスク → 高優先)

### Phase 3: 計画書作成

**出力形式:**
`docs/plannings/YYYY-MM-DD_comprehensive-refactoring-plan.md`

詳細なテンプレートは [references/plan-template.md](references/plan-template.md) を参照。

## 出力の特徴

1. **チェックボックス形式**: 進捗追跡可能
2. **Phase 分割**: 依存関係を考慮した段階的計画
3. **具体的な指摘**: ファイル名と行番号を含む (= `path/to/file.py:L10`)
4. **改善案の提示**: 各問題に対する解決方法

## 実行タイミング

- 月 1 回の定期実行
- メジャーリリース前の品質チェック
- 大きな機能追加後 (= 新しい Stage / プロバイダ追加など)
- リファクタリング週間の開始時

## 注意事項

- 調査には時間がかかるため余裕を持って実行
- 緊急対応項目 (= Critical) は即座に報告
- 計画は段階的に実施することを前提
- 既存テスト (= `tests/` 配下 80+ ファイル) を grandfathered として尊重し、一気にリファクタしない
