# Tensyoku Movie Generator

転職系ショート動画を自動生成する日本語特化ツール。

## プロジェクトの前提

- コンテンツテーマは **career-change（転職）** に限定。他テーマ・他言語は扱わない。
- 台本は `screenplays/<名前>.json` に配置する。人間が手で書くか、`scripts/analyze_video.py` で参考動画から自動生成する。
- 動画生成は **段階的ゲート方式**。台本作成後、`python main.py <台本名>` を起動するたびに **1ステージだけ** 実行して停止する。プレビューUIで成果物を確認・承認するまで次stageに進まない。一括生成モードは存在しない。

## 段階的ゲート方式 (7ステージ)

```
[1.台本] → [2.TTS] → [3.背景] → [4.Kling] → [5+6.シーン動画] → [7.字幕] → [完成]
```

各stageの成果物は `output/<TS>/tmp/` に保存され、進捗は `tmp-progress.json` で管理する。プレビューUIで承認するまで次stageは実行できない。

### 操作フロー

```bash
# サーバを起動
python3 preview_server.py            # http://127.0.0.1:5555 (バックエンド)
cd frontend && npm run dev           # http://localhost:5173 (フロント開発)
# または `npm run build` 後はサーバが /frontend/dist を配信

# UIで「プロジェクト作成」 → Stage 1完了。承認すると次stageが自動起動
# CLIから手動で進めることも可:
python3 main.py <台本>                # 新規TS生成 + Stage 1実行
python3 main.py <台本> --resume <TS>  # 既存TSの次stageを実行
```

### ステージ別の成果物

| Stage      | アーティファクト                                     | 主な確認内容                                     |
| ---------- | ---------------------------------------------------- | ------------------------------------------------ |
| 1. script  | `metadata.json` + 台本検証                           | caption/title_overlay/シーン構成/lines整合性     |
| 2. tts     | `tmp/tts_<S>_<L>.mp3`                                | 各セリフの発音/感情/速度/voice_id                |
| 3. bg      | `tmp/bg_<S>.png`                                     | 構図・キャラ一貫性・字幕領域(下部)への被写体侵入 |
| 4. kling   | `tmp/kling_<S>.mp4` + `tmp/scene_<S>.trim.mp4`       | 動き・キャラ崩壊・動作完了点                     |
| 5+6. scene | `tmp/scene_<S>.mp4`                                  | TTS音声付き+リップシンク済みの完成シーン動画     |
| 7. overlay | `tmp/overlaid.mp4`                                   | 字幕の表示位置・タイミング・視認性               |
| final      | `output/reels_<TS>.mp4` + `post_captions/<title>.md` | BGM mix済み完成動画                              |

### 個別シーンの再生成

UIから各シーンカードの「再生成」ボタンで個別シーンのみ再実行できる。再生成すると当該stageの承認はリセットされ、再度OK判定が必要。

| stage              | 再生成単位              |
| ------------------ | ----------------------- |
| tts                | line単位 / scene単位    |
| bg / kling / scene | scene単位               |
| overlay            | 全体 (字幕情報のみ変更) |

## 必読ドキュメント

台本を書く前・動画企画を立てる前に必ず `docs/content-strategy.md` を読むこと。実装作業に入る前には `docs/development-rules.md` を読むこと。

- `docs/content-strategy.md` — **動画制作の根本戦略**。Transformation / コンテンツ軸 / POV / MVP / 最適化
- `docs/development-rules.md` — 開発ルール・前提事項・禁止事項
- `docs/architecture-decisions.md` — AIモデル選定、プラットフォーム選定、コスト構造、プロンプト最適化、ワークフロー設計

## 台本JSONの仕様

`screenplays/<名前>.json` は次のスキーマで記述する（`scenes[].lines[]` 構造、リッチメタデータ完全版）:

```json
{
  "caption": "会社選びが何より大切です\n\n#未経験 #it業界 #転職",
  "title_overlay": "未経験から\nITエンジニアに転職した末路",
  "audio_mode": "voiced",
  "bgm_path": "/abs/path/assets/bgm/<name>_bgm.wav",
  "bgm_volume_db": -18,
  "wardrobe_continuity": {
    "office_outfit": "グレーのリブニット + ブラックパンツ + 眼鏡 + ロングヘア"
  },
  "scenes": [
    {
      "time": "9:00",
      "label": "始業",
      "duration": 5.0,
      "background_prompt": "モダンなオフィスで駆け寄るエンジニア cinematic lighting, shallow depth of field",
      "animation_prompt": "subject rushes to desk, opens laptop, leans back relieved",
      "character_refs": ["female_engineer"],
      "characters": [
        {
          "name": "主人公",
          "role": "narrator",
          "ref": "female_engineer",
          "outfit": "グレーニット"
        }
      ],
      "wardrobe": {
        "identifier": "office_outfit",
        "top": "リブニット",
        "hair": "ロング"
      },
      "facial_expression": "焦って早口、目を見開く",
      "hand_gesture": "ノートPCのキーボードを叩く",
      "lipsync": true,
      "lines": [
        {
          "text": "やばいやばい",
          "start": 0.0,
          "end": 1.0,
          "emotion": "焦り",
          "delivery": "早口で小声",
          "rate": "+10%",
          "voice_overrides": { "stability": 0.25 },
          "pronunciation_hints": { "IT": "アイティー" }
        }
      ]
    }
  ]
}
```

### フィールド仕様

| ルート          | 型                       | 説明                                             |
| --------------- | ------------------------ | ------------------------------------------------ |
| `caption`       | string(必須)             | SNS投稿用キャプション本文＋ハッシュタグ          |
| `title_overlay` | string(任意)             | 動画上部固定の黄色帯タイトル。`\n`改行可         |
| `audio_mode`    | `"voiced"` \| `"silent"` | 既定`voiced`。silentはTTS/リップシンクをスキップ |
| `scenes[]`      | array(必須)              | シーン配列。各シーン=1Klingクリップ              |

| シーン              | 説明                                                                                                                   |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `time`              | 画面下部の大文字時刻（例 `"8:50"`）                                                                                    |
| `label`             | 時刻の下の日本語ラベル（例 `"起床"`）                                                                                  |
| `duration`          | シーン秒数（3以上）。Klingは5/10sで生成し台本値にtrim                                                                  |
| `background_prompt` | Imagen用。被写体=日本語+スタイル修飾=英語                                                                              |
| `animation_prompt`  | Kling V3用（英語推奨）。シーン全体の動きを1文で                                                                        |
| `character_refs`    | `characters/<名前>.png`を参照。既定は`config.DEFAULT_CHARACTER_REFS` (= `["female_engineer"]`)。キャラ無しは`[]`を明示 |
| `lipsync`           | 既定true。silent時は無視                                                                                               |
| `lines[]`           | シーン内のセリフ配列                                                                                                   |

| ライン                | 説明                                                                                                                       |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `text`                | セリフ。ASCIIの `,` `.` 禁止（validatorで拒否）。全角句読点/括弧はTTS直前に自動除去                                        |
| `start`               | シーン内相対秒でのセリフ開始                                                                                               |
| `end`                 | 字幕消滅秒（TTS長とは独立。表示用）                                                                                        |
| `rate`                | TTS速度（例 `"+10%"`）。指定時は`emotion`プリセットと`acoustic.wpm`の自動算出を上書き                                      |
| `emotion`             | `config.EMOTION_VOICE_PRESETS`のキーと対応。自動でTTS paramとKling motion addon適用                                        |
| `delivery`            | 話し方の自然言語記述。`config.DELIVERY_TAG_ENABLED=True`なら eleven_v3 inline tag として `[delivery] text` 形式でTTSへ送信 |
| `acoustic`            | librosa由来のpitch/rms/wpm。**自動活用**: `wpm`→rate算出、`pitch_trend`→style微調整、`rms_peak`→ffmpeg音量±dB              |
| `voice_overrides`     | 特定lineに限定したElevenLabs paramの明示上書き。`emotion`プリセットより優先                                                |
| `pronunciation_hints` | TTS送信前のテキスト置換（例 `{"IT": "アイティー"}`）                                                                       |
| `pause_before`        | このline直前に挿入する無音秒数（タイミング遅延）                                                                           |
| `breath_before`       | true なら `BREATH_DEFAULT_DURATION` 秒分の遅延を入れる（吸気間）                                                           |
| `speaker`             | 発話者。`scenes[].characters[].name` と対応（複数キャラシーン用）                                                          |

| シーン拡張          | 説明                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------ |
| `characters[]`      | 登場人物。`name` / `role` / `ref` / `outfit`。`ref` は `characters/<ref>.png` を参照 |
| `wardrobe`          | 服装。`identifier` を `wardrobe_continuity` のキーと一致させると複数シーン間で統一   |
| `facial_expression` | シーン主役の表情。Imagen + Kling プロンプトに自動展開                                |
| `hand_gesture`      | シーン主役の手の動き。同上                                                           |

| ルート拡張            | 説明                                                                  |
| --------------------- | --------------------------------------------------------------------- |
| `bgm_path`            | 全編に流すBGM音声ファイル絶対パス。指定時はvoiceの下に低音量で自動mix |
| `bgm_volume_db`       | BGMの相対音量dB。既定 -18                                             |
| `wardrobe_continuity` | 衣装識別子→説明 のマップ。`scenes[].wardrobe.identifier` と紐付け     |

## 参考動画から台本を自動生成する

参考動画(.mov/.mp4)を Claude Opus 4.7 + Whisper + librosa + PySceneDetect + demucs で逆算し、`scenes[].lines[]` JSON を吐き出す:

```
python3 scripts/analyze_video.py path/to/reference.mov
# → screenplays/auto_reference.json が生成される
python3 scripts/analyze_video.py path/to/reference.mov --instructions "TikTok UIは無視"
python3 scripts/analyze_video.py path/to/reference.mov --no-bgm-extract --no-shots
```

- フレーム抽出は **0.5秒刻み** が既定（`--fps 2.0`）。変更可能
- 音声: Whisper でword単位のtranscript取得（`OPENAI_API_KEY`が無ければ `faster-whisper` ローカル推論にフォールバック）
- librosa で各phraseの pitch/rms/wpm に加え、無音区間・呼吸音・話者プロファイル・BGM存在判定を抽出
- demucs (なければ HPSS) で BGM を分離して `assets/bgm/<name>_bgm.wav` に保存し、screenplay に `bgm_path` として紐付け
- 全素材を Claude Opus 4.7 (1M context) に渡して統合推論。出力には characters/wardrobe/facial_expression/hand_gesture も含む
- 所要コスト: 約250〜400円/本（フレーム数に応じて変動）
- 必要な環境変数: `ANTHROPIC_API_KEY` 必須。`OPENAI_API_KEY` は任意（無ければローカル whisper）

## 感情→TTS/モーション自動適用

`scenes[].lines[].emotion`に以下のいずれかを入れると、`config.EMOTION_VOICE_PRESETS`と`config.EMOTION_MOTION_ADDONS`から自動でTTSパラメータとKlingアニメーションキーワードが適用される:

`驚き / 喜び / 焦り / 落胆 / 中立 / 満足 / 困惑 / 怒り / 恥ずかしさ`

手動で細かく制御したい場合は `voice_overrides` で個別に上書き。

## 自動活用される音響メタデータ

`acoustic` の各値は scene_gen で以下のように自動消費される:

| メタ                             | 使われ方                                                                   |
| -------------------------------- | -------------------------------------------------------------------------- |
| `acoustic.wpm`                   | `WPM_BASELINE`(=280) を基準に `rate` を自動算出。`rate` 明示があれば上書き |
| `acoustic.pitch_trend`           | `rising`→TTS style +0.10、`falling`→-0.05                                  |
| `acoustic.rms_peak`              | <0.30→TTS音声を `-6dB` で生成、>0.55→`+3dB`。中間は手付かず                |
| `delivery`                       | `[delivery] text` の inline tag として eleven_v3 へ送信                    |
| `pause_before` / `breath_before` | line開始タイミングを遅らせて間を作る                                       |

## 話者プロファイル → voice_id 自動選択

`_analysis.voice_profile`（analyze_video.py が自動付与）から:

- pitch_hz_median × estimated_gender → `config.VOICE_LIBRARY` の中から最も近いElevenLabs voice を選択
- 個別 `voice_overrides.voice_id` があればそちら優先

## オーバーレイ

最終動画には **字幕 (lines[].text) のみ** を焼き込む。タイトル帯/時刻表示/ラベル/インサート画像/ポップアップなどのオーバーレイは廃止。

`title_overlay` / `scenes[].time` / `scenes[].label` フィールドは残しているが画面には描画されない。台本のメタ情報（分析DB保存・参考動画解析時のフック表現）として活用される。

## BGM ミックス

screenplay ルートに `bgm_path` があれば `compose_video` 最終段で voice 下に低音量 (`bgm_volume_db` 既定 -18dB) で自動 mix。silent モードでは無視。

## ログ

`logging` モジュール経由で出力される。`LOG_LEVEL` 環境変数でレベル変更、`LOG_FILE` でファイル出力可。

## リップシンクプロバイダー

`config.LIPSYNC_PROVIDER` で切替。既定は `domoai` (顎の崩れが少ない)。

| provider   | API key          | モデル                      | エンドポイント                                   |
| ---------- | ---------------- | --------------------------- | ------------------------------------------------ |
| `domoai`   | `DOMOAI_API_KEY` | `talking-avatar-v1` (既定)  | `https://api.domoai.com/v1/video/talking-avatar` |
| `fal-sync` | `FAL_KEY`        | `lipsync-1.9.0-beta` (既定) | `fal-ai/sync-lipsync`                            |

DomoAI に切替えるだけなら `.env` に `DOMOAI_API_KEY=<key>` を入れるだけで動作する。プロバイダ自体を変えたい場合は `LIPSYNC_PROVIDER=fal-sync` を `.env` に追加。

DomoAI の制約: 出力動画は **1〜60s**。シーン音声が 60s を超える場合は 60s に clamp して送信される (warning ログ)。

## 分析基盤（Analytics）

SQLiteベースの台本×動画×投稿×メトリクス管理基盤。`data/analytics.db` に保存。

### 運用フロー

```
# 1. 台本をDBに登録＋Claude Haikuでhook/tone/emotion/theme等を自動タグ付け
python3 scripts/ingest_screenplay.py screenplays/19_xxx.json

# 2. 生成した動画をDBに登録（metadata.jsonから台本と紐付け）
python3 scripts/ingest_video.py 20260425_123456

# 3. 各プラットフォームへ投稿後、投稿URLをDBに登録
python3 scripts/register_post.py 20260425_123456 youtube https://youtube.com/shorts/abc
python3 scripts/register_post.py 20260425_123456 instagram https://www.instagram.com/reel/xxx
python3 scripts/register_post.py 20260425_123456 tiktok <tiktok_post_id>

# 4. YouTube成績を取得（cron推奨、Instagram/TikTokは未対応）
python3 scripts/fetch_metrics.py --platform youtube

# 5. ダッシュボード閲覧
streamlit run scripts/dashboard.py
```

### 必要な環境変数

```
# 分析ツール
OPENAI_API_KEY=...              # scripts/analyze_video.py
ANTHROPIC_API_KEY=...           # scripts/analyze_video.py / ingest_screenplay.py (auto_tag)

# YouTube
YOUTUBE_API_KEY=...             # 公開統計（views/likes/comments等）
YOUTUBE_OAUTH_CLIENT_ID=...     # Analytics API（完遂率・視聴時間等、要OAuth）
YOUTUBE_OAUTH_CLIENT_SECRET=...
YOUTUBE_REFRESH_TOKEN=...       # 初回認可後の refresh token

# analytics DBの保存先（任意、既定: data/analytics.db）
ANALYTICS_DB_PATH=/absolute/path/analytics.db
```

### データモデル

- `screenplays` — 台本 + 自動タグ（hook_type/tone/dominant_emotion/theme/character_archetype）
- `videos` — 生成動画、台本IDで紐付け
- `posts` — 投稿（YouTube/Instagram/TikTok）、video_idで紐付け
- `post_metrics` — 時系列メトリクス、post_idで紐付け
- `v_performance` — 横断ビュー（台本×動画×投稿×最新メトリクス）

Instagram・TikTokのAPI連携は未実装。必要になったら `platform_clients/` に追加する。

## コマンド一覧

```
# 生成（段階的ゲート方式: 1回起動につき1ステージ実行）
python3 main.py <台本>                                    新規TS発行 + Stage 1 実行
python3 main.py <台本> --resume TS                        既存TSの次stage実行

# プレビューUI
python3 preview_server.py                                  バックエンド (http://127.0.0.1:5555)
cd frontend && npm install && npm run build               フロントビルド (初回のみ)
cd frontend && npm run dev                                 フロント開発サーバ (http://localhost:5173)

# 分析
python3 scripts/analyze_video.py <参考動画>               参考動画から台本を逆算生成

# 投稿と成績管理
python3 scripts/ingest_screenplay.py <台本.json>          DB登録+自動タグ
python3 scripts/ingest_video.py <TS>                      DB登録（台本と紐付け）
python3 scripts/register_post.py <video_id> <platform> <URL>
python3 scripts/fetch_metrics.py [--platform youtube]     最新メトリクス取得
streamlit run scripts/dashboard.py                         ダッシュボード
```
