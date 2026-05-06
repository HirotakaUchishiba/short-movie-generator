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

**Stage 1「台本」ページの「素材編集」セクション** — analyze 経由で作成されたプロジェクト (= `metadata.json` に `analyze_job_id` がある) では、Stage 1 ページ上部に **参考動画 (read-only) / 抽象台本 (caption + 登場人物 + 話者マッピング + シーン別 lines)** が表示される。話者マッピングは Claude が振った匿名 `speaker_1, speaker_2, ...` を実 character ref に対応付ける UI で、ここを 1 回設定するだけで各シーンの登場人物と各 line の voice_overrides が自動推論される。手書き台本プロジェクト (analyze_job_id 無し) では話者マッピングは表示されず、Stage 1 は完全 screenplay の確認のみとなる。

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

| Stage      | アーティファクト                                     | 主な確認内容                                                                                                                                                        |
| ---------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. script  | `metadata.json` + 台本検証                           | caption/シーン構成/lines 整合性 (analyze 経由なら同ページ上部で 参考動画 / 抽象台本 / 話者マッピングも編集可能。保存時は Stage 1〜7 の承認のみ解除し assets は保持) |
| 2. tts     | `tmp/tts_<S>_<L>.mp3`                                | 各セリフの発音/感情/速度/voice_id                                                                                                                                   |
| 3. bg      | `tmp/bg_<S>.png`                                     | 構図・キャラ一貫性・字幕領域(下部)への被写体侵入                                                                                                                    |
| 4. kling   | `tmp/kling_<S>.mp4` + `tmp/scene_<S>.trim.mp4`       | 動き・キャラ崩壊・動作完了点                                                                                                                                        |
| 5+6. scene | `tmp/scene_<S>.mp4`                                  | TTS音声付き+リップシンク済みの完成シーン動画                                                                                                                        |
| 7. overlay | `tmp/overlaid.mp4`                                   | 字幕の表示位置・タイミング・視認性                                                                                                                                  |
| final      | `output/reels_<TS>.mp4` + `post_captions/<title>.md` | BGM mix済み完成動画                                                                                                                                                 |

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
- `docs/abstract-screenplay-design.md` — **抽象台本生成 + compose 合成** の設計 (analyze pipeline は構成・セリフ・感情・話者だけ抽出し、ビジュアルは scene 個別の `location_ref` / `character_selection` / `animation_style` で注入)

## 台本JSONの仕様

### 保存先 (template / project snapshot)

台本は **2 つの場所** に存在する:

| 種別                 | パス                        | git 管理 | 用途                                                                                                                                                             |
| -------------------- | --------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **template**         | `screenplays/<名前>.json`   | 追跡     | 新規 project 作成時の素材 (素の手書き台本 / analyze pipeline 出力 / StyleEditorPage の compose 結果)                                                             |
| **project snapshot** | `temp/<TS>/screenplay.json` | ignore   | project 作成時に template からコピーされる **immutable な作業コピー**。Stage 1〜7 のすべて、UI の line/scene patch、再合成は **このファイルだけ** を読み書きする |

ポイントは **project 作成時に template から snapshot がコピーされ、以後 template が外部で書き換わっても進行中 project は影響を受けない** こと:

- analyze pipeline 二重実行で template が変わっても、進行中 project の screenplay は不変
- UI の編集 (caption / lines / location_ref など) は project snapshot だけを更新。他 project に影響しない
- 「素材編集」での再合成 (`POST /api/projects/<TS>/recompose`) も project snapshot を更新するだけ。template は触らない

#### 読み書きの API (`staged_pipeline`)

| 関数                                   | 読み書き対象                | 用途                                                        |
| -------------------------------------- | --------------------------- | ----------------------------------------------------------- |
| `load_template(name)`                  | `screenplays/<name>.json`   | 新規 project 作成時の素材ロード (= POST /api/projects) のみ |
| `load_project_screenplay(ts_path)`     | `temp/<TS>/screenplay.json` | 後 stage / UI / 再合成 — **読み取りはすべてこれ**           |
| `save_project_screenplay(ts_path, sp)` | `temp/<TS>/screenplay.json` | **書き込みもすべてこれ**。metadata.json の sha も同時に更新 |

旧 `screenplays/drafts/` ディレクトリと `save_screenplay(name, sp)` は廃止。既存 project は `scripts/migrate_to_project_snapshot.py` で snapshot に移行する (一度だけ実行)。

`scripts/analyze_video.py` は **template 直下** (`screenplays/auto_<sha>.json`) に書き出す (= 新規 project の素材として、後で create-project 経由で snapshot 化される)。

### スキーマ (2 SSOT 分離)

責務を 2 つに分離。VideoStyle は廃止 (= 各 scene が animation_style / location_ref / character_selection を直接持つ)。

| SSOT                   | 場所                                 | 内容                                                                |
| ---------------------- | ------------------------------------ | ------------------------------------------------------------------- |
| **キャラエンティティ** | `characters/<base>/...` (ネスト)     | 全身参照画像 (衣装バリアント) と voice メタ                         |
| **ロケ集**             | `locations/<id>.json` + .preview.png | 1 ロケ = decor + lighting + color_palette + props + camera_distance |

#### `characters/` ディレクトリ構造

```
characters/
  f1/                      ← 被写体 ID (= 顔・体型・髪型が同じ人物)。職業など役割は名前に含めない
    voice.json             ← voice メタ (= base 単位で 1 つ。衣装で声は変わらない)
    base.png               ← 衣装サフィックス無しでこの ID を参照したときの画像
    office.png             ← `f1__office` で参照される衣装バリアント
    casual.png             ← `f1__casual` で参照される
    preview.png            ← (任意) UI 一覧表示用のサムネ
  m1/
    voice.json
    suit.png
    casual.png
```

screenplay の `character_refs` / `featured_characters` には **解決済み ID** (= `<base>__<wardrobe>`、衣装無しなら `<base>` 単独) を入れる。`/asset/character/<resolved>` は新ネスト構造を優先し、見つからなければ旧 flat (= `characters/<resolved>.png`) にフォールバックする。

#### キャラ画像のガイドライン

- アスペクト比: **9:16 縦長** (= 動画と同じ)
- 構図: **全身、正面、棒立ちか自然な立ち姿**。両手は体の横
- 表情: 中立 (= 笑顔/しかめ面は emotion 系プロンプトで上書きする想定)
- 背景: **白〜薄グレーの単色** (= location_ref の背景に置換しやすくするため)
- 解像度: 882×1568 以上

理由: camera_distance (close-up / medium-close / medium / wide) のすべてに同じ参照画像で対応するため。肩から上だけだと medium / wide で下半身を Imagen が想像で補完して衣装が崩れる。

#### キャラ voice メタ (= `characters/<base>/voice.json`) のスキーマ

```json
{
  "id": "f1",
  "voice_overrides": { "voice_id": "...", "stability": 0.4, "style": 0.3 }
}
```

`id` は base ID のみ (`__wardrobe` を含めない)。compose で resolved ID から base に剥がして読む。

完全 screenplay (= `screenplays/<名前>.json`) のスキーマ:

```json
{
  "caption": "会社選びが何より大切です\n\n#未経験 #it業界 #転職",
  "scenes": [
    {
      "location_ref": "home_office",
      "background_prompt": "デスクに駆け寄るエンジニア cinematic lighting, shallow depth of field",
      "animation_prompt": "subject rushes to desk, opens laptop, leans back relieved",
      "character_refs": ["f1__office"],
      "characters": [{ "name": "f1__office" }],
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

`duration` は Stage 2 (TTS) が実音声長から書き込む派生値。Stage 1 抽象台本には書かない。

ロケ詳細 (= `locations/<id>.json`) のスキーマ:

```json
{
  "id": "home_office",
  "decor": "ミニマル北欧風、ナチュラルウッドのデスク、観葉植物、白壁、奥にアートと窓",
  "lighting": "柔らかい自然光、暖色系",
  "color_palette": "白基調、ベージュ、グリーンのアクセント",
  "props": "シルバーのMacBook、白いマグカップ",
  "camera_distance": "medium-close"
}
```

ロケのサムネは `locations/<id>.preview.png` に置く。`POST /api/locations/<id>/preview` で Imagen から自動生成可能 (= LocationPicker の「🪄 生成」ボタン)。

### フィールド仕様

| ルート     | 型           | 説明                                    |
| ---------- | ------------ | --------------------------------------- |
| `caption`  | string(必須) | SNS投稿用キャプション本文＋ハッシュタグ |
| `scenes[]` | array(必須)  | シーン配列。各シーン=1Klingクリップ     |

| シーン              | 説明                                                                                                                                                                                                      |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `duration`          | シーン秒数。Stage 2 (TTS) が実音声長から自動算出する派生値。Stage 1 では書かない                                                                                                                          |
| `background_prompt` | Imagen用。被写体=日本語+スタイル修飾=英語。`location_ref` がある場合はロケ情報がプロンプト先頭に自動注入される                                                                                            |
| `location_ref`      | グローバル `locations/<id>.json` のキー。ロケ整合性 (装飾/光/色/小物/カメラ距離) を自動注入                                                                                                               |
| `animation_prompt`  | Kling V3用（英語推奨）。シーン全体の動きを1文で                                                                                                                                                           |
| `character_refs`    | `characters/<base>/<wardrobe>.png` を参照。**解決済み ref** (例: `f1__office`) を入れる。衣装無しは `<base>` 単独 (= `base.png` を参照)。キャラ無しは `[]` を明示。既定は `config.DEFAULT_CHARACTER_REFS` |
| `lipsync`           | 既定true。silent時は無視                                                                                                                                                                                  |
| `lines[]`           | シーン内のセリフ配列                                                                                                                                                                                      |

| ライン                | 説明                                                                                                                       |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `text`                | セリフ。ASCIIの `,` `.` 禁止（validatorで拒否）。全角句読点/括弧はTTS直前に自動除去                                        |
| `start`               | シーン内相対秒でのセリフ開始。Stage 2 (TTS) が実音声長から自動算出する派生値。Stage 1 では編集しない                       |
| `end`                 | セリフ末尾の相対秒。Stage 2 (TTS) が実音声長から自動算出する派生値。Stage 1 では編集しない                                 |
| `rate`                | TTS速度（例 `"+10%"`）。指定時は`emotion`プリセットと`acoustic.wpm`の自動算出を上書き                                      |
| `emotion`             | `config.EMOTION_VOICE_PRESETS`のキーと対応。自動でTTS paramとKling motion addon適用                                        |
| `delivery`            | 話し方の自然言語記述。`config.DELIVERY_TAG_ENABLED=True`なら eleven_v3 inline tag として `[delivery] text` 形式でTTSへ送信 |
| `acoustic`            | librosa由来のpitch/rms/wpm。**自動活用**: `wpm`→rate算出、`pitch_trend`→style微調整、`rms_peak`→ffmpeg音量±dB              |
| `voice_overrides`     | 特定lineに限定したElevenLabs paramの明示上書き。`emotion`プリセットより優先                                                |
| `pronunciation_hints` | TTS送信前のテキスト置換（例 `{"IT": "アイティー"}`）                                                                       |

| シーン拡張        | 説明                                                                                     |
| ----------------- | ---------------------------------------------------------------------------------------- |
| `characters[]`    | 登場人物。`name` のみ (= 解決済み ref と一致)。表示・LLM 補助用                          |
| `camera_distance` | シーンごとの寄り引き (close-up / medium-close / medium / wide)。ロケのデフォルトを上書き |

### ロケ詳細 (`locations/<id>.json` のフィールド)

| 属性              | 説明                                                        |
| ----------------- | ----------------------------------------------------------- |
| `decor`           | 家具・壁・床・建材などのレイアウト記述                      |
| `lighting`        | 光源・色温度・影の質感 (指定時は emotion 由来を抑止)        |
| `color_palette`   | 全体の配色トーン                                            |
| `props`           | 小道具 (PC, マグカップ, 書類 等)                            |
| `camera_distance` | 推奨カメラ距離 (close-up / medium-close / medium / wide 等) |

各属性は `background_prompt` の **先頭** に "location decor: ..." 等のラベル付きで自動注入される。シーンごとの `background_prompt` は被写体の動作・表情のみ書き、装飾はロケに寄せると一貫性が保てる。ロケはグローバル管理 (= `locations/<id>.json`) で全動画で共有されるため、編集すると全動画に影響する。微調整が必要なら新しい id を作る運用。

## 参考動画から台本を自動生成する

参考動画(.mov/.mp4)を Claude Opus 4.7 + Whisper + librosa で逆算し、抽象台本 JSON を吐き出す:

```
python3 scripts/analyze_video.py path/to/reference.mov
# → screenplays/auto_reference.json が生成される
python3 scripts/analyze_video.py path/to/reference.mov --instructions "TikTok UIは無視"
```

- フレーム抽出は **0.5秒刻み** が既定（`--fps 2.0`）。変更可能
- 音声: Whisper でword単位のtranscript取得（`OPENAI_API_KEY`が無ければ `faster-whisper` ローカル推論にフォールバック）
- librosa で各phraseの pitch/rms/wpm を抽出
- 全素材を Claude Opus 4.7 (1M context) に渡して統合推論。出力は **抽象台本** (構成・セリフ・感情・匿名 speaker_N のみ、ビジュアル要素は scene 個別フィールド + speaker_to_ref で後段に注入)。詳細は `docs/abstract-screenplay-design.md`
- 所要コスト: 約250〜400円/本（フレーム数に応じて変動）
- 必要な環境変数: `ANTHROPIC_API_KEY` 必須。`OPENAI_API_KEY` は任意（無ければローカル whisper）

## 感情→TTS/モーション自動適用

`scenes[].lines[].emotion`に以下のいずれかを入れると、`config.EMOTION_VOICE_PRESETS`と`config.EMOTION_MOTION_ADDONS`から自動でTTSパラメータとKlingアニメーションキーワードが適用される:

`驚き / 喜び / 焦り / 落胆 / 中立 / 満足 / 困惑 / 怒り / 恥ずかしさ`

手動で細かく制御したい場合は `voice_overrides` で個別に上書き。

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
