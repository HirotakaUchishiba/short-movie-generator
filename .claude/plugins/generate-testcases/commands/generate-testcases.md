---
description: 手動 QA テストケースを生成する。機能を分析し、YAML 形式でテストケースを生成。
argument-hint: 対象機能 (例: Stage 6 字幕プレビュー、Stage 7 final import watchdog)
---

# QA テストケース生成

機能やコードを分析し、**手動 QA** テスト用のテストケースを YAML 形式で生成します。preview UI の承認フロー (= 自動 pytest で代替できない領域) を主対象とします。

対象機能: $ARGUMENTS

---

## 設計原則

### 1. 手動 QA の役割を理解する

手動 QA はテストピラミッドの「E2E 層」に相当する。

- **数を絞る**: 重要なユーザーフローに集中する
- **密度を上げる**: 類似パターンは 1 ケースのステップで複数カバーする (例: 3 種の感情を各ステップで確認)。同じ観点の正常 / 異常は 1 ケースにまとめる。1 機能あたり最大 35 件程度を目安とする
- **意味のあるテストを実施する**: 過剰な境界値テストやユーザーにとってクリティカルではないテストケースは優先度を下げ、最終的な結果の整合性を重視する (= 字幕タイミング、音声品質、キャラ一貫性など)

### 2. リスクベースでケースを選定する

全パターン網羅は目指さない。以下の観点で重要なケースに絞る:

- **ユーザー影響**: 失敗すると視聴者にバレる項目を優先 (= キャラ崩壊 / 音声歪み / 字幕オーバーラップ)
- **発生頻度**: よく踏むフロー (= analyze 経由 project の Stage 1 編集) を優先
- **過去の不具合**: 以前 reject した不良 (= `data/qa_failures/`) を重点的に
- **成果物の内容正確性を最優先**: UI の操作性 (= ボタンの活性 / disabled) よりも、最終出力 (= `output/reels_<TS>.mp4` の音声 / 字幕) の正確性を重視

### 3. ユーザーの操作フロー順にグルーピングする

- テストケースは **ユーザーが実際に操作する順序** でグルーピングする (例: プロジェクト作成 → Stage 承認 → 再生成 → final 取込)
- 1〜2 件しかないセクションは関連セクションに吸収する
- 同一セクション内で正常系 → 異常系の順にする

### 4. 内部実装ではなく観察可能な結果で記述する

- テストケースは **ユーザーが画面上で確認できる結果** で書く
- 内部実装の概念 (= `progress_store` / `screenplay_lock` / `tracker.handle`) を使わない
- 例: ×「`progress_store.mark_approved` が呼ばれる」 → ○「次の stage カードが活性化する」

### 5. 期待結果は具体的に、入力値は必要に応じて

- **期待結果**: 必ず具体的に書く (「正しく表示される」 → 「caption の最初の 1 行に絵文字付きフックが表示される」)
- **入力値**: 検証対象なら具体的に、そうでなければ「任意の値」で OK
- **前提条件の数量**: scene 数 / line 数に検証上の意味がない場合は「scene が 1 つ以上ある状態」と書く。テスト実行者のデータ準備コストを最小化する

### 6. UI のラベル・ボタンテキストは実装と正確に一致させる

- テストケースに記載するラベル名やボタンテキストは、**必ずコードの実装を確認** して正確な文言を使用する
- 「再生成」と「再生成する」のような微妙な差異もテスト実行者を混乱させるため、実装と完全に一致させる

### 7. テストケースのスコープを対象機能に限定する

- 対象機能のスコープ外のテストケースは含めない
- 関連する別機能 (例: Stage 6 字幕のテストに、Stage 4 Kling 再生成のテストを含める等) は、その機能専用のテストケースファイルに分離する

### 8. テストの信頼性を担保する

| 問題   | 内容                           | 対策                                     |
| ------ | ------------------------------ | ---------------------------------------- |
| 偽陽性 | 問題ないのにテストが失敗する   | 環境依存・タイミング依存のケースを避ける |
| 偽陰性 | バグがあるのにテストが成功する | 期待値を具体的に書く                     |

---

## Phase 1: 対象の特定とコード分析

**Goal**: 対象機能のコード・画面・API を特定し、テスト設計の材料を揃える

**Actions**:

1. レイヤの特定: pipeline (CLI / `staged_pipeline`) / preview UI (`frontend`) / analytics / final_import / publish のどれか
2. コードの分析: 関連するコード・画面・API を調査
   - 関連するエンドポイント (= `preview_server.py` の `@app.route(...)`)
   - 関連する React コンポーネント (= `frontend/src/...`)
   - 関連する pipeline 関数
   - バリデーションルール (= `screenplay_validator.py` / `dataclass`)
   - エラーハンドリング (= `try/except` の境界)

---

## Phase 2: テストケース設計

**Goal**: 機能の性質に応じた検証観点を洗い出す

機能の種類に応じて、以下から該当する観点を選定する (すべてを網羅する必要はない):

| 観点                                                 | 該当する機能の例                                   |
| ---------------------------------------------------- | -------------------------------------------------- |
| データの作成・読取・更新・削除                       | screenplay 編集、metadata.json、`final_versions[]` |
| バリデーション (必須、形式、範囲)                    | screenplay_validator のルール                      |
| 出力結果の正確性 (= 動画の音声 / 字幕 / キャラ)      | Stage 5 / Stage 6 / Stage 7 の最終物               |
| 状態遷移 (generated → approved → next stage 解除)    | progress_store のゲート                            |
| 表示条件 (analyze_job_id 有無で「素材編集」表示変化) | Stage 1 ページの条件付き UI                        |
| エッジケース (空 scene、長すぎる line、特殊文字)     | screenplay validator                               |
| 音声品質 (silence ratio、平均 dB、clipping)          | Stage 2 TTS                                        |
| 動画品質 (キャラ崩壊、ストーリーボード検出)          | Stage 3 / Stage 4                                  |
| クロスプラットフォーム互換性 (= ffmpeg / pbcopy)     | Stage 7 / Stage 8 の半自動 publish                 |

---

## Phase 3: YAML 生成・ファイル出力

**Goal**: テストケースを YAML 形式で生成し出力する

**IMPORTANT**: 生成前に、このプラグインと同じディレクトリの `reference.yaml` (もし存在すれば) を読み、フォーマット・トーン・粒度を合わせること。無い場合は適宜きれいに揃える。

**命名規則**:

- **ID**: `[A-Z]{2}-[0-9]{3}` (2 文字 prefix + 3 桁番号)
- **ファイル名**: `機能名.yaml` (例: `stage6-overlay.yaml`)

**出力先**:

- pipeline (CLI) 系: `docs/tests/manual/pipeline/`
- preview UI 系: `docs/tests/manual/ui/`
- final_import / publish 系: `docs/tests/manual/post-production/`
- analytics 系: `docs/tests/manual/analytics/`

**既存ファイルがある場合**:

- 既存の cases に追加 (ID の重複に注意)
- 最大 ID を確認して連番を継続

---

## Phase 4: 網羅性チェック

**Goal**: 生成したテストケースの網羅性を検証

**CRITICAL**: このフェーズでは必ず coverage-checker エージェントを起動すること。

**Actions**:

1. **coverage-checker エージェントを起動**して以下を依頼:
   - 生成した YAML ファイルのパス
   - 対象機能の実装コードのパス (= `staged_pipeline.py` / `preview_server.py` の関連エンドポイント)
   - 網羅性チェックを実行

2. エージェントからの報告を確認:
   - 漏れがあれば追加ケースを作成
   - 問題なければ完了

---

## ID Prefix 例

Stage 単位の prefix を基本とし、横断機能は別途。

| Prefix | 機能                                | 主担当                |
| ------ | ----------------------------------- | --------------------- |
| SC     | Stage 1: 台本編集 / 検証            | preview UI + CLI      |
| TT     | Stage 2: TTS                        | pipeline + preview UI |
| BG     | Stage 3: 背景生成                   | pipeline + preview UI |
| KL     | Stage 4: Kling                      | pipeline + preview UI |
| SN     | Stage 5: scene 合成 (= lipsync)     | pipeline + preview UI |
| OV     | Stage 6: 字幕 / overlay             | preview UI            |
| FI     | Stage 7: final_import               | watchdog + UI + CLI   |
| PB     | Stage 8: publish                    | YouTube / IG / TikTok |
| AN     | analyze pipeline                    | CLI + preview UI      |
| AT     | analytics / dashboard               | scripts               |
| UI     | preview UI 全般 (= 横断 navigation) | frontend              |

新しい機能は適切な 2 文字 prefix を決めて追加する。
