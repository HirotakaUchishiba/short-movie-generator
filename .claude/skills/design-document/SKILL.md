---
name: design-document
description: 機能・基盤の設計書を作成する。WHY/WHAT/HOWに集中し、具体的な実装コードは最小限に。スコープを明確化し、実装タスクをチェックリスト形式で記載。
allowed-tools: Read, Write, Glob, Grep, WebSearch, WebFetch
---

# 設計書作成スキル

機能や基盤の設計書を `docs/plannings/` に作成します。実装の「なぜ・何を・どう」を明確にし、具体的なコード例は最小限に抑えます。

## 発動条件

以下のような要求で発動:

- 「設計書を書いて」「設計してください」
- 新機能・基盤の実装前
- アーキテクチャ変更の検討時

## 7つの設計原則

### 1. スコープの明確化

- 今回やること・やらないことを明示
- 将来の拡張は Phase 2 以降として分離
- 関連機能への言及は最小限

### 2. 具体的なコードは最小限

- 型定義は簡潔に (パラメータと戻り値のみ)
- 関数の責務を文章で説明
- WHY / WHAT / HOW を説明

### 3. 技術選定が決まっている場合

- 前提として扱い、比較表は不要
- 冒頭で明記するのみ

### 4. 実装例は動的で実用的に

- サンプルは固定文言でなく動的に
- Debug 画面・テスト機能を含める

### 5. 不要なセクションは削除

- 成功指標・KPI は基盤構築時は不要
- 技術選定の比較表は確定時は不要

### 6. 命名はシンプルに

- 不要な prefix は付けない
- パッケージ名でスコープを明確に

### 7. ドキュメント構造のルール

- ordered list で記述
- 実装タスクは checkbox 形式
- ファイル命名: `YYYY-MM-DD_feature-name.md`
- 配置: `docs/plannings/`

## ワークフロー

1. **ヒアリング**: ユーザーの要求を理解、スコープを確認
2. **調査**: 既存の設計書 (`docs/plannings/`) ・コードベースを調査
3. **執筆**: テンプレートに沿って記述 (WHY / WHAT / HOW)
4. **レビュー**: フィードバックを受けて修正

## 参考資料

詳細は以下を参照:

- [テンプレート](references/template.md): 設計書の構成テンプレート
- [具体例](references/examples.md): 良い例・悪い例の比較

## tensyoku 固有の補足

- フロー文書は **`docs/plannings/YYYY-MM-DD_*.md`**、静的設計は **`docs/developments/*.md`** という分離を尊重する (= `docs/developments/coding-rules.md` §11)
- 8-stage パイプライン (= script / TTS / bg / kling / scene / overlay / final_import / publish) に関わる設計は、`docs/developments/architecture.md` のレイヤと依存方向に整合させる
- 用語は `docs/developments/ubiquitous-language.md` の対応表を遵守する

## 注意事項

- 実装の詳細は実装時に考える (設計段階では方針のみ)
- 完璧を目指さない (実装しながら調整する前提)
- スコープクリープに注意
- ユーザーのフィードバックは無条件で受け入れるのではなく、吟味して妥当性を検討した上で判断する
