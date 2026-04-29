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
| 1. script  | `metadata.json` + 台本検証                           | caption/シーン構成/lines整合性                   |
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

### 保存先と canonical / drafts 分離

台本は **2 層構造**:

| 層        | パス                             | git 管理 | 用途                                     |
| --------- | -------------------------------- | -------- | ---------------------------------------- |
| canonical | `screenplays/<名前>.json`        | 追跡     | 確定版。コードレビュー / 動画投稿の根拠  |
| drafts    | `screenplays/drafts/<名前>.json` | ignore   | UI / preview_server が編集を保存する WIP |

**読み込み順 (`staged_pipeline.screenplay_path`)**: `drafts/<名前>.json` があれば最優先、無ければ canonical。これにより UI の編集中状態が動画生成にそのまま反映される。**書き込み (`staged_pipeline.save_screenplay`)** は常に drafts/。`drafts/` は `.gitignore` で追跡対象外なので、UI 編集を繰り返しても working tree は汚れない。drafts ディレクトリは無ければ初回 save 時に自動生成。

**確定版に昇格** (drafts → canonical) させたい時は手動コピー後 commit:

```bash
cp screenplays/drafts/<名前>.json screenplays/<名前>.json
git add screenplays/<名前>.json
git commit -m "content(<id>): ..."
```

drafts を捨てて canonical の状態に戻したい時は:

```bash
rm screenplays/drafts/<名前>.json
```

`scripts/analyze_video.py` などのスクリプトは canonical 直下に書き出す (= 新規台本として人間レビュー前提)。

### スキーマ

`screenplays/<名前>.json` は次のスキーマで記述する（`scenes[].lines[]` 構造、リッチメタデータ完全版）:

```json
{
  "caption": "会社選びが何より大切です\n\n#未経験 #it業界 #転職",
  "audio_mode": "voiced",
  "bgm_path": "/abs/path/assets/bgm/<name>_bgm.wav",
  "bgm_volume_db": -18,
  "wardrobe_continuity": {
    "office_outfit": "グレーのリブニット + ブラックパンツ + 眼鏡 + ロングヘア"
  },
  "location_continuity": {
    "home_office": {
      "decor": "ミニマル北欧風、ナチュラルウッドのデスク、観葉植物、白壁、奥にアートと窓",
      "lighting": "柔らかい自然光、暖色系",
      "color_palette": "白基調、ベージュ、グリーンのアクセント",
      "props": "シルバーのMacBook、白いマグカップ (PC画面は反射のみで内容は描かない)",
      "camera_distance": "medium-close"
    }
  },
  "scenes": [
    {
      "label": "始業",
      "duration": 5.0,
      "location_ref": "home_office",
      "background_prompt": "デスクに駆け寄るエンジニア cinematic lighting, shallow depth of field",
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

| ルート       | 型                       | 説明                                             |
| ------------ | ------------------------ | ------------------------------------------------ |
| `caption`    | string(必須)             | SNS投稿用キャプション本文＋ハッシュタグ          |
| `audio_mode` | `"voiced"` \| `"silent"` | 既定`voiced`。silentはTTS/リップシンクをスキップ |
| `scenes[]`   | array(必須)              | シーン配列。各シーン=1Klingクリップ              |

| シーン              | 説明                                                                                                                   |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `label`             | シーンの日本語ラベル（例 `"起床"`）。動画には焼き込まれず、UI/LLM 補助情報                                             |
| `duration`          | シーン秒数（3以上）。Klingは5/10sで生成し台本値にtrim                                                                  |
| `background_prompt` | Imagen用。被写体=日本語+スタイル修飾=英語。`location_ref` がある場合はロケ情報がプロンプト先頭に自動注入される         |
| `location_ref`      | `root.location_continuity` のキー。同一動画内のロケ整合性 (装飾/光/色/小物/カメラ距離) を自動注入                      |
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

| シーン拡張          | 説明                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------ |
| `characters[]`      | 登場人物。`name` / `role` / `ref` / `outfit`。`ref` は `characters/<ref>.png` を参照 |
| `wardrobe`          | 服装。`identifier` を `wardrobe_continuity` のキーと一致させると複数シーン間で統一   |
| `facial_expression` | シーン主役の表情。Imagen + Kling プロンプトに自動展開                                |
| `hand_gesture`      | シーン主役の手の動き。同上                                                           |

| ルート拡張            | 説明                                                                                              |
| --------------------- | ------------------------------------------------------------------------------------------------- |
| `bgm_path`            | 全編に流すBGM音声ファイル絶対パス。指定時はvoiceの下に低音量で自動mix                             |
| `bgm_volume_db`       | BGMの相対音量dB。既定 -18                                                                         |
| `wardrobe_continuity` | 衣装識別子→説明 のマップ。`scenes[].wardrobe.identifier` と紐付け                                 |
| `location_continuity` | ロケ識別子→属性辞書のマップ。`scenes[].location_ref` と紐付け、同一動画内で背景の一貫性を自動確保 |

### `location_continuity` のフィールド

| 属性              | 説明                                                        |
| ----------------- | ----------------------------------------------------------- |
| `decor`           | 家具・壁・床・建材などのレイアウト記述                      |
| `lighting`        | 光源・色温度・影の質感 (指定時は emotion 由来を抑止)        |
| `color_palette`   | 全体の配色トーン                                            |
| `props`           | 小道具 (PC, マグカップ, 書類 等)                            |
| `camera_distance` | 推奨カメラ距離 (close-up / medium-close / medium / wide 等) |

各属性は `background_prompt` の **先頭** に "location decor: ..." 等のラベル付きで自動注入される。シーンごとの `background_prompt` は被写体の動作・表情のみ書き、装飾はロケに寄せると一貫性が保てる。動画ごとに `location_continuity` を自由に再定義してよい (ディレクトリ事前生成不要)。

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
- librosa で各phraseの pitch/rms/wpm に加え、BGM存在判定を抽出
- demucs (なければ HPSS) で BGM を分離して `assets/bgm/<name>_bgm.wav` に保存し、screenplay に `bgm_path` として紐付け
- 全素材を Claude Opus 4.7 (1M context) に渡して統合推論。出力には characters/wardrobe/facial_expression/hand_gesture も含む
- 所要コスト: 約250〜400円/本（フレーム数に応じて変動）
- 必要な環境変数: `ANTHROPIC_API_KEY` 必須。`OPENAI_API_KEY` は任意（無ければローカル whisper）

## 感情→TTS/モーション自動適用

`scenes[].lines[].emotion`に以下のいずれかを入れると、`config.EMOTION_VOICE_PRESETS`と`config.EMOTION_MOTION_ADDONS`から自動でTTSパラメータとKlingアニメーションキーワードが適用される:

`驚き / 喜び / 焦り / 落胆 / 中立 / 満足 / 困惑 / 怒り / 恥ずかしさ`

手動で細かく制御したい場合は `voice_overrides` で個別に上書き。

## 日本語修正案でプロンプトを書き換える (Stage 3 / Stage 4)

Stage 3 (背景) と Stage 4 (Kling) のシーンカードに「日本語で修正案を入力」パネルがあり、日本語の修正指示 (例: "もっとカメラを引いて、机にマグカップ追加") を Claude Sonnet に渡して **既存の `background_prompt` / `animation_prompt` を最小差分で書き換える**。

- **preview**: LLM を呼んで diff を表示。変更前/変更後を見比べ、変更後はテキスト編集可能
- **適用**: 採用した prompt を screenplay の該当フィールドに書き戻す (= 以降は手書き扱いで Stage 実行に使われる)

UI 誘発語 (chat bubble / notification 等) が出力に含まれていたら自動でリジェクトする。LLM モデルは `PROMPT_REVISE_MODEL` (既定 `claude-sonnet-4-6`) で切替可能。

## 自動活用される音響メタデータ

`acoustic` の各値は scene_gen で以下のように自動消費される:

| メタ                   | 使われ方                                                                   |
| ---------------------- | -------------------------------------------------------------------------- |
| `acoustic.wpm`         | `WPM_BASELINE`(=280) を基準に `rate` を自動算出。`rate` 明示があれば上書き |
| `acoustic.pitch_trend` | `rising`→TTS style +0.10、`falling`→-0.05                                  |
| `acoustic.rms_peak`    | <0.30→TTS音声を `-6dB` で生成、>0.55→`+3dB`。中間は手付かず                |
| `delivery`             | `[delivery] text` の inline tag として eleven_v3 へ送信                    |

## オーバーレイ

最終動画には **字幕 (lines[].text) のみ** を焼き込む。タイトル帯/時刻表示/ラベル/インサート画像/ポップアップなどのオーバーレイは廃止。

`scenes[].label` は動画には描画されない。シーン識別用のメタ情報として UI 表示と LLM 補助入力に使われる。

### 字幕の手動チャンク制御

各 line に `subtitles: [{text, start?, end?}]` を指定すると、その line に対する自動分割 (`_split_into_chunks`) を **完全にスキップ** し、ここに書かれた通りのチャンクで字幕を焼き込む。`start` / `end` (シーン内相対秒) は **両方 optional** で、両方指定 (= 手打ち) または両方省略 (= auto) のいずれか。片方だけは validator で reject。`scene_videos` の実尺と `duration` が乖離している場合 (slow_mo 等) は line と同じく ratio 比でリスケールされる。

| chunk の time   | 動作                                                                                             |
| --------------- | ------------------------------------------------------------------------------------------------ |
| 両方省略 (auto) | line.start - line.end の中で、前後の固定境界 (= 手打ち time or line 端) との間を文字数比例で配分 |
| 両方指定        | その値を絶対の境界として使用 (隣接 auto chunks のアンカーになる)                                 |

`compositor._resolve_subtitle_timings` がアンカー方式で混在ケースを解決する: line 端 + 手打ち start/end を境界として固定し、間に挟まる auto chunks を文字数比例で埋める。文字数 0 の auto chunks は均等割にフォールバック。

Stage 7 UI (`StageOverlay.tsx`) では:

- line 行で「手動に切替」: subtitles[] を `[{text: line.text}]` で初期化 (時刻は auto)
- 各チャンクの「分割」「+ チャンク追加」「× 削除」でチャンク構造を編集 (text だけで OK)
- **動画プレイヤーの再生位置をスナップ**: 各チャンクの「⏱→start」「⏱→end」ボタンで `video.currentTime - sceneOffsets[sIdx]` をその場でセット。微調整したい境界だけ動画と同期できる
- 「auto に戻す」: そのチャンクの time を削除して文字数比例配分に戻す
- 「自動に戻す」: subtitles 自体を削除して `_split_into_chunks` 経路に戻す

## BGM ミックス

screenplay ルートに `bgm_path` があれば `compose_video` 最終段で voice 下に低音量 (`bgm_volume_db` 既定 -18dB) で自動 mix。silent モードでは無視。

## ログ

`logging` モジュール経由で出力される。`LOG_LEVEL` 環境変数でレベル変更、`LOG_FILE` でファイル出力可。

## リップシンクプロバイダー

`config.LIPSYNC_PROVIDER` で切替。既定は `syncso` (Sync.so 公式 lipsync-2)。

| provider   | API key          | モデル                      | エンドポイント                                                              |
| ---------- | ---------------- | --------------------------- | --------------------------------------------------------------------------- |
| `syncso`   | `SYNC_API_KEY`   | `lipsync-2` (既定)          | `https://api.sync.so/v2/generate` (multipart) + `/v2/generate/{id}` polling |
| `domoai`   | `DOMOAI_API_KEY` | `talking-avatar-v1` (既定)  | `https://api.domoai.com/v1/video/talking-avatar`                            |
| `fal-sync` | `FAL_KEY`        | `lipsync-1.9.0-beta` (既定) | `fal-ai/sync-lipsync`                                                       |

Sync.so 既定で動かすなら `.env` に `SYNC_API_KEY=<key>` を入れるだけ。プロバイダを変える場合は `LIPSYNC_PROVIDER=domoai` か `fal-sync` を追加。

Sync.so のモデル切替: `SYNCSO_LIPSYNC_MODEL` で `lipsync-2` / `lipsync-2-pro` (高品質) / `lipsync-1.9.0-beta` (高速) / `react-1` (短尺感情) / `sync-3` から選択。

### 制約

- **Sync.so**: multipart 上限 1 ファイル 20MB。シーン動画 / audio はこの範囲に収まる前提
- **DomoAI**: 出力 1〜60s。60s 超えは clamp (warning ログ)

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
