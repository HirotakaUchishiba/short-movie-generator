# アーキテクチャ・意思決定記録

本ドキュメントは本プロジェクトの採用技術・構成の根拠を記述する。

---

## 1. コンテンツ領域

- テーマ: 特定領域に固定しない
- 言語: 日本語のみ
- フォーマット: 9:16 ショート動画（Instagram Reels / TikTok / YouTube Shorts）

## 2. 台本の扱い

- 台本 (`screenplays/<名前>.json`) は **`scripts/analyze_video.py` が参考動画から逆算生成する** (= 現状の唯一の作成経路。新規 screenplay を起こす UI / API は無く、手書き経路は廃止済み)
- プロジェクト側は台本を「入力」として受け取り、動画を「出力」する責務のみを持つ
- 台本の自動生成・アイデア出し・ブレインストーミング支援はスコープ外 (= analyze pipeline で参考動画から逆算する場合を除く)

## 3. モデル・API選定

| API                                        | 用途                 | 認証               | 単価      |
| ------------------------------------------ | -------------------- | ------------------ | --------- |
| Google Gemini (gemini-3-pro-image-preview) | 背景画像生成         | GOOGLE_API_KEY     | $0.134/枚 |
| ElevenLabs v3 (eleven_v3)                  | 日本語TTS            | ELEVENLABS_API_KEY | プラン内  |
| fal.ai Kling V3 Standard I2V               | I2Vアニメーション    | FAL_KEY            | $0.084/秒 |
| FFmpeg                                     | シーン結合・字幕合成 | ローカル           | -         |

### 動画生成: Kling V3 Standard

- 9:16対応、3〜15秒、1080p
- I2V（Image-to-Video）品質で ELO 上位
- 全シーン同一モデルで生成する（モデル切替によるスタイル不整合を避けるため）

### TTS: ElevenLabs v3 multilingual

- `language_code=ja` を指定
- `with-timestamps` エンドポイントで文字単位のタイムスタンプを取得
- タイムスタンプは字幕の表示タイミングに直結する

### プラットフォーム集約方針

動画生成APIは fal.ai に集約する。理由:

- 複数プロバイダーを管理するコスト > 単価差の節約
- モデル切替がエンドポイント文字列の変更のみで可能
- 課金ダッシュボードが1つにまとまる

---

## 4. ワークフロー設計

現行の段階的ゲート方式 (8 ステージ: script / tts / bg / kling / scene / overlay / final_import / publish) と各ステージの成果物・承認フロー・個別シーン再生成 UI は `CLAUDE.md` を参照。

---

## 5. コスト構造

### 1動画あたり概算

| シーン数 | 動画長 | 背景コスト | 動画コスト | 合計   |
| -------- | ------ | ---------- | ---------- | ------ |
| 10       | 40秒   | $1.34      | $3.36      | ~$4.70 |
| 14       | 60秒   | $1.88      | $5.04      | ~$6.92 |

- 背景: シーン固有の `background_prompt` の数だけ生成（同一プロンプトはキャッシュ共有）
- 動画: セグメントごとの音声長さに合わせて生成秒数が決まる
- 音声: ElevenLabs プラン内で課金なし

実消費額は fal.ai ダッシュボードで照合する。リトライやタイムアウトで理論値を上回ることがある。

### cost_tracking モジュール

**記録 / 見積もり / レポート** を分離する設計:

- **記録**: 各 stage の API 呼び出し直後に `cost_tracking.recorder` が `data/cost_records.jsonl` に append-only で書き込む。記録失敗はパイプライン本流を止めない (= `try / except` 隔離)
- **単価カタログ**: `data/pricebook.json` (運用者管理) — provider 公式料金に追従して手で更新する。コードに単価ハードコードは置かない
- **見積もり**: `cost_tracking.estimator` が実コスト履歴から per-unit median を取って算定。履歴 < 3 件なら `confidence="insufficient"` を返し、catalog fallback はしない
- **レポート**: `cost_tracking.report` がプロジェクト別 / 全体の集計を提供
- **為替**: `JPY_PER_USD` 環境変数 > `pricebook.json#jpy_per_usd` (既定 150)

主要 API:

- `GET /api/cost/pricebook` — 単価カタログ
- `GET /api/cost/median/<stage>?model=...` — 履歴 median rate (frontend で units × rate)
- `GET /api/cost/estimate/<stage>?model=...&...` — 動的見積もり
- `GET /api/cost/report/project/<ts>` — プロジェクト別実コスト
- `GET /api/cost/report` — 全体レポート

### コスト削減の方針

- シーン数・動画長は台本のテキスト量で自然に決まる。無理に短くしない
- 品質を下げるモデル切替はしない
- コスト削減したい場合は台本のテキスト量を調整する

---

## 6. プロンプト設計

### `background_prompt`（各シーン必須）

- 被写体とスタイル修飾の両方を各シーンごとに記述する（自動連結なし）
- 被写体は日本語で記述する（日本特有のモチーフも正確に伝わる）
- スタイル修飾は英語で記述する（cinematic lighting, shallow depth of field, warm tones 等、Gemini の出力が安定する）
- `no text, no letters, vertical portrait composition` は `scene_gen` が自動付与する

### `animation_prompt`（各シーン任意）

- 英語で記述する（Kling V3は英語プロンプトで最もよく動く）
- 「どう動くか」だけを書く。背景プロンプトの繰り返しを含めない
- 具体的な動詞を使う

例:

- NG: `"gentle cinematic motion, photorealistic close-up of a resume..."`
- OK: `"slow dramatic zoom into the resume on the desk, soft light shifts across the printed text"`

---

## 7. 日本語字幕システム

### フォント

ヒラギノ角ゴシック W7（`config.FONT_PATH`）、78pt、縁取り6px。日本語の画数に耐える太さと視認性を優先。

### 分割方針

- ElevenLabs から返る文字単位タイムスタンプを 8 文字単位でグルーピングしてテロップ化
- 文区切り（`。！？`）・節区切り（`、,`）を優先した分割
- 最大 14 文字/行、最小 4 文字/行

### キーワード強調

`keyword_extractor.py` が台本テキストから以下を自動抽出:

- カタカナ3文字以上の連続
- 漢字2文字以上の連続
- `「」『』` で括られた2〜12文字
- `#タグ` 形式の明示キーワード

抽出したキーワードは黄色・サイズ拡大で ASS 字幕に反映される。

---

## 8. ファクトチェック

- 価格情報はブログ記事を鵜呑みにせず、各サービスの公式料金ページを直接確認する
- 「最高品質」「最安」などの主張には必ずソースを付ける
- 確認できない情報は「未検証」と明記する
