# Tensyoku Movie Generator

転職系ショート動画を自動生成する日本語特化ツール。

## プロジェクトの前提

- コンテンツテーマは **career-change（転職）** に限定。他テーマ・他言語は扱わない。
- 台本は `screenplays/<名前>.json` に配置する。人間が手で書くか、`scripts/analyze_video.py` で参考動画から自動生成する。
- 動画生成は **段階的ゲート方式**。台本作成後、`python main.py <台本名>` を起動するたびに **1ステージだけ** 実行して停止する。プレビューUIで成果物を確認・承認するまで次stageに進まない。一括生成モードは存在しない。

## 段階的ゲート方式 (8ステージ)

```
[1.台本] → [2.TTS] → [3.背景] → [4.Kling] → [5.音声/リップシンク合成] → [6.字幕 (= pipeline raw)]
                                                                                ↓
                                                                       [CapCut 等で手動編集]
                                                                                ↓
                                                                   [7.取込] → [8.公開 (YouTube/IG/TikTok)]
```

各stageの成果物は `temp/<TS>/tmp/` に保存され、進捗は `tmp-progress.json` で管理する。プレビューUIで承認するまで次stageは実行できない。

**Stage 6 まで** はパイプラインが自動で生成し、UI 承認で次に進む完全自動。Stage 6 (字幕) の生成完了時に pipeline raw である `output/reels_<TS>.mp4` と SNS キャプションも同時に書き出される。**Stage 7 / 8** はユーザの外部アクション (= CapCut で編集 → ドロップ、プラットフォームに公開) が起点で、`run-next` では自動起動しない。

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

| Stage           | アーティファクト                                                          | 主な確認内容                                                                                                                                                        |
| --------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. script       | `metadata.json` + 台本検証                                                | caption/シーン構成/lines 整合性 (analyze 経由なら同ページ上部で 参考動画 / 抽象台本 / 話者マッピングも編集可能。保存時は Stage 1〜6 の承認のみ解除し assets は保持) |
| 2. tts          | `tmp/tts_<S>_<L>.mp3`                                                     | 各セリフの発音/感情/速度/voice_id                                                                                                                                   |
| 3. bg           | `tmp/bg_<S>.png`                                                          | 構図・キャラ一貫性・字幕領域(下部)への被写体侵入                                                                                                                    |
| 4. kling        | `tmp/kling_<S>.mp4` + `tmp/scene_<S>.trim.mp4`                            | 動き・キャラ崩壊・動作完了点                                                                                                                                        |
| 5. scene        | `tmp/scene_<S>.mp4`                                                       | 音声 / リップシンク合成済みの完成シーン動画                                                                                                                         |
| 6. overlay      | `tmp/overlaid.mp4` + `output/reels_<TS>.mp4` + `post_captions/<title>.md` | 字幕の表示位置・タイミング・視認性。生成時に pipeline raw (`reels_<TS>.mp4`) と SNS キャプションも同時に書き出される                                                |
| 7. final_import | `temp/<TS>/final/<HHMMSS>.mp4` (複数バージョン)                           | CapCut 編集後の動画。watchdog が `final/` への drop を自動検知 + 音声指紋で誤投入を検出。canonical を選んで承認すると Stage 8 へ                                    |
| 8. publish      | `metadata.json.published_posts[]` + analytics DB                          | YouTube は Data API resumable upload で自動投稿、IG/TikTok は半自動 (caption をクリップボードへ + アプリ起動)。成功時に `posts` テーブルに登録される                |

### 個別シーンの再生成

UIから各シーンカードの「再生成」ボタンで個別シーンのみ再実行できる。再生成すると当該stageの承認 + 後続 stage (kling/scene/overlay) の承認も連鎖リセットされ、再度 OK 判定が必要。

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
| **project snapshot** | `temp/<TS>/screenplay.json` | ignore   | project 作成時に template からコピーされる **immutable な作業コピー**。Stage 1〜6 のすべて、UI の line/scene patch、再合成は **このファイルだけ** を読み書きする |

ポイントは **project 作成時に template から snapshot がコピーされ、以後 template が外部で書き換わっても進行中 project は影響を受けない** こと:

- analyze pipeline 二重実行で template が変わっても、進行中 project の screenplay は不変
- UI の編集 (caption / lines / location_ref など) は project snapshot だけを更新。他 project に影響しない
- 「素材編集」での再合成 (`PUT /api/projects/<ts>/abstract`) も project snapshot を更新するだけ。template は触らない

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

| ライン                | 説明                                                                                                                                                             |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `text`                | セリフ。ASCIIの `,` `.` 禁止（validatorで拒否）。全角句読点/括弧はTTS直前に自動除去                                                                              |
| `start`               | シーン内相対秒でのセリフ開始。Stage 2 (TTS) が実音声長から自動算出する派生値。Stage 1 では編集しない                                                             |
| `end`                 | セリフ末尾の相対秒。Stage 2 (TTS) が実音声長から自動算出する派生値。Stage 1 では編集しない                                                                       |
| `emotion`             | 感情ラベル。`config.EMOTION_AUDIO_TAGS` のキーが eleven_v3 inline tag (`[surprised]` 等) として line.text 先頭に自動挿入される + Kling motion addon が適用される |
| `audio_tags`          | eleven_v3 inline tag を line 単位で手動指定 (例: `["whispers"]`, `["shouts"]`)。emotion 由来のタグと併用される                                                   |
| `delivery`            | 話し方の自然言語記述。`config.DELIVERY_TAG_ENABLED=True`なら eleven_v3 inline tag として `[delivery] text` 形式でTTSへ送信                                       |
| `emotion_intensity`   | `soft` / `normal` / `strong`。analyzer / UI 編集メタとして保持されるが TTS パラメータには反映されない (= one-shot TTS 制約)                                      |
| `acoustic`            | analyze pipeline 由来の pitch/rms/wpm。表示・LLM 補助入力用 (TTS には反映されない)                                                                               |
| `pronunciation_hints` | TTS送信前のテキスト置換（例 `{"IT": "アイティー"}`）                                                                                                             |

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
- 所要コストは `data/cost_records.jsonl` の履歴 median から動的算定 (履歴 < 3 件は "履歴不足" 表示)。単価カタログは `data/pricebook.json` (運用者管理)
- 必要な環境変数: `ANTHROPIC_API_KEY` 必須。`OPENAI_API_KEY` は任意（無ければローカル whisper）

## 感情 → inline tag / Kling motion 自動適用

`scenes[].lines[].emotion` に以下のいずれかを入れると、ElevenLabs eleven_v3 の inline audio tag (`config.EMOTION_AUDIO_TAGS`) が line.text 先頭に `[surprised]` 等の形で自動挿入され、Kling animation_prompt にも `config.EMOTION_MOTION_ADDONS` 由来のモーションキーワードが追加される:

`驚き / 喜び / 焦り / 落胆 / 中立 / 満足 / 困惑 / 怒り / 恥ずかしさ`

per-line で voice 表現を細かく制御したい場合は `audio_tags[]` (例: `["whispers"]`, `["shouts"]`, `["crying"]`) を直接指定する。`config.AVAILABLE_AUDIO_TAGS` に候補一覧がある。

## TTS の制約 (one-shot 経路)

Stage 2 は **screenplay 全体を 1 ElevenLabs API call** で生成する (= `generate_screenplay_tts_one_shot`)。連続音声で char-level timestamps を取得することで line 境界を silence-detect で snap し、自然な抑揚と pacing を実現している。

このため:

- `voice_id` / `stability` / `similarity_boost` / `style` / `speed` は **screenplay-wide で 1 セット** (= `config.ELEVENLABS_*` グローバル + `TTS_GLOBAL_SPEED`)。per-line 切替不可
- per-line の表現切替は **inline tag だけ** で行う (= `audio_tags[]`, `emotion`, `delivery`)
- analyze pipeline が記録する `acoustic.wpm` / `pitch_trend` / `rms_peak` は表示・LLM 補助用で TTS パラメータには反映されない

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

Stage 6 UI (`StageOverlay.tsx`) では:

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
- **DomoAI**: 出力 1〜60s。60s 超えは LipsyncClientError raise (= fallback chain で次プロバイダへ)

## Stage 7 取込 + Stage 8 公開 (CapCut → SNS の自動化)

Stage 6 で生成された `output/reels_<TS>.mp4` を CapCut 等で手動編集し、編集後の動画を pipeline に戻して analytics + 公開につなげるためのフェーズ。

### Stage 7: final import の発火 3 経路

| 経路                     | 入口                                                                            | TS 同定                |
| ------------------------ | ------------------------------------------------------------------------------- | ---------------------- |
| **A. watchdog** (既定)   | `temp/<TS>/final/*.mp4` にドロップ → size 安定 3 秒で自動取込                   | パスから抽出           |
| **B. UI ドロップゾーン** | `/api/projects/<TS>/final` (multipart upload) または Stage 7 ページの drag&drop | エンドポイントから取得 |
| **C. CLI**               | `python3 main.py --resume <TS> --import-final <path>`                           | 引数で明示             |

3 経路は `final_import.import_final(ts, src, source)` 共通ハンドラに集約。受信時に音声指紋検証 (`final_import.fingerprint.compute_match_score`) で「pipeline 出力の TTS 音声がこの動画にも残っているか」を [0, 1] で記録。閾値 (0.6) 未満は UI で警告のみ表示し、取込は続行する。

`temp/<TS>/final/<HHMMSS>.mp4` に複数バージョンを保管できる。`metadata.json.final_versions[]` で is_canonical を管理し、analytics / publish の正本は canonical なファイルが指される。`DISABLE_FINAL_WATCHER=1` で watchdog を無効化可能。

### Stage 8: 公開フロー

| platform            | 自動化                                           | 必要な env                                                                                                                                   |
| ------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **YouTube Shorts**  | 完全自動 (Data API resumable upload)             | `YOUTUBE_OAUTH_CLIENT_ID` / `_CLIENT_SECRET` / `_REFRESH_TOKEN` (`youtube.upload` スコープ同意必須)                                          |
| **Instagram Reels** | 半自動 (caption をクリップボードへ + アプリ起動) | (Phase 1 では env 不要。Graph API 自動化は `INSTAGRAM_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ID` で `platform_clients/instagram.py` がスタブ済) |
| **TikTok**          | 半自動 + CSV 取込                                | (Phase 1 では env 不要。Display API は `TIKTOK_ACCESS_TOKEN` + `TIKTOK_OPEN_ID`、CSV は `scripts/ingest_tiktok_csv.py`)                      |

YouTube は upload 成功時に `analytics.posts` に自動登録 (= `register_post.py` を叩かなくて良い)。IG/TikTok は半自動なので、アップロード完了後にユーザが URL を `register_post.py` で投入する。`fetch_metrics.py` は YouTube/IG/TikTok の 3 platform に対応 (= IG/TikTok は env 設定後に有効)。

```bash
# Stage 7 (CapCut 出力の取込)
python3 main.py --resume 20260506_120000 --import-final ~/Desktop/edited.mp4
python3 main.py --resume 20260506_120000 --list-finals
python3 main.py --resume 20260506_120000 --canonical 142233.mp4   # canonical 切替

# Stage 8 (公開)
python3 main.py --resume 20260506_120000 --publish youtube --privacy unlisted
python3 main.py --resume 20260506_120000 --publish instagram     # 半自動

# TikTok Studio CSV 取込 (= 暫定の metrics 取得)
python3 scripts/ingest_tiktok_csv.py path/to/video_performance.csv
```

## 分析基盤（Analytics）

SQLiteベースの台本×動画×投稿×メトリクス管理基盤。`data/analytics.db` に保存。

### 運用フロー

```
# 1. 台本をDBに登録＋Claude Haikuでhook/tone/emotion/theme等を自動タグ付け
python3 scripts/ingest_screenplay.py screenplays/19_xxx.json

# 2. 生成した動画をDBに登録（metadata.jsonから台本と紐付け）
#    canonical な final があれば自動でそちらを output_path にする (= --prefer raw で raw 強制可)
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
