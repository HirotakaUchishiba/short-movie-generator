# Tensyoku Movie Generator

転職系ショート動画（Instagram Reels / TikTok / YouTube Shorts）の自動生成ツール。日本語音声・日本語字幕に特化。

人間が手動で作成した台本JSONを入力として、背景画像生成 → 日本語TTS → Kling V3動画生成 → ASS字幕合成 → SNS投稿キャプション出力までを一気通貫で処理する。

## ドキュメント

- `docs/content-strategy.md` — **動画制作の根本戦略**（Transformation / MVP / 最適化）。企画と台本の考え方はすべてここから
- `docs/development-rules.md` — 開発ルール・前提事項・禁止事項
- `docs/architecture-decisions.md` — 採用技術・API・ワークフロー設計の意思決定

## セットアップ

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# .env に GOOGLE_API_KEY / ELEVENLABS_API_KEY / FAL_KEY を設定
```

## 使い方

### 1. 台本を作成する

`screenplays/<名前>.json` を手動で作成する。スキーマは [台本JSONフォーマット](#台本jsonフォーマット) を参照。

### 2. 動画を生成する

```bash
# 一気通貫で生成
python main.py <台本名>

# 途中から再開（タイムスタンプは初回実行時の標準出力に表示される）
python main.py <台本名> --resume <TS>

# 特定セグメントだけ再生成
python main.py <台本名> --resume <TS> --redo 2,7,8
python main.py <台本名> --resume <TS> --redo 2:bg,7:bg
python main.py <台本名> --resume <TS> --redo 8:audio
python main.py <台本名> --resume <TS> --redo 1:bg,2:sub,9:bg+sub+audio
```

実行開始時にコスト・時間の予想が表示され、完了時に実績と共に `reports/report_<TS>.md` へ記録される。`reports/cost_history.jsonl` に実績が蓄積され、次回以降の見積もりはこれを元に自動校正される。

### 3. Preview UI で確認・再生成する

```bash
python preview_server.py
# → http://127.0.0.1:5555
```

ブラウザでセグメント単位にサムネイルを確認し、気になる箇所だけ注記付きで再生成できる。Redoジョブは `reports/jobs/<JOB_ID>.json` に永続化され、サーバ再起動をまたいで状態が残る。

### テスト実行

```bash
python -m pytest tests/
```

## 台本JSONフォーマット

```json
{
  "caption": "会社選びが何より大切です\n\n#未経験 #it業界 #転職",
  "scenes": [
    {
      "background_prompt": "モダンなオフィス、スーツ姿のビジネスパーソン、シネマティックライティング",
      "animation_prompt": "slow dramatic zoom into the resume on the desk",
      "segments": [
        {
          "text": "転職を考えているあなたへ",
          "emotion": "落ち着いて語りかける",
          "rate": "+5%"
        }
      ]
    }
  ]
}
```

**フィールド:**

| フィールド                    | 必須 | 内容                                                                                  |
| ----------------------------- | ---- | ------------------------------------------------------------------------------------- |
| `caption`                     | ○    | SNS投稿用キャプション本文（ハッシュタグ含む、そのまま `post_captions/` に出力される） |
| `scenes[].background_prompt`  | ○    | 被写体（日本語可）とスタイル修飾（英語推奨、cinematic lighting 等）を両方記述         |
| `scenes[].animation_prompt`   | 任意 | Kling V3へのアニメーション指示（英語推奨）                                            |
| `scenes[].segments[].text`    | ○    | TTS音声・字幕のテキスト。`,` `.` は禁止                                               |
| `scenes[].segments[].emotion` | 任意 | TTSの感情指示（ElevenLabs v3 voice_settings に影響）                                  |
| `scenes[].segments[].rate`    | 任意 | 発話速度。`+10%` 等                                                                   |
| `scenes[].segments[].static`  | 任意 | `true` で黒背景（プロンプト不要）                                                     |
| `scenes[].character_refs`     | 任意 | `characters/<名前>.png` を参照キャラ画像として渡す。例: `["protagonist"]`             |

`caption` は動画末尾のCTAやハッシュタグを含む完成形のテキストを直接記述する。生成パイプラインは改変せずそのまま `post_captions/<名前>.md` に出力する。

## キャラクター一貫性

`characters/<名前>.png` に参照キャラクター画像を配置し、台本の `scenes[].character_refs` で名前を指定すると、Gemini に参照として同梱される。動画シリーズで同じ主人公を繰り返し使う場合にブランド一貫性が保てる。

```
characters/
├── protagonist.png       # 主人公
├── interviewer_male.png  # 面接官
└── mentor.png            # メンター役
```

参照画像がディレクトリにない場合は警告ログのみ出し、画像なしで通常生成される。

## 短尺セグメントの自動統合

`segments[].text` が `config.MIN_SEGMENT_CHARS`（既定 15 文字）未満のセグメントが **同一シーン内で隣接** する場合、`main.py` が自動的に `。` で結合して 1 つのセグメントにまとめる。fal.ai Kling V3 の最小 3 秒課金による無駄を抑制する狙い。シーン境界を跨ぐ統合は行わない。

## 使用API

| API             | 用途                                                 |
| --------------- | ---------------------------------------------------- |
| Google Gemini   | 背景画像生成                                         |
| ElevenLabs v3   | 日本語TTS（language=ja、文字単位タイムスタンプ出力） |
| fal.ai Kling V3 | 画像+プロンプト → アニメーション動画                 |
| FFmpeg          | シーン結合・ASS字幕合成・最終合成                    |

## --redo オプション

| 対象    | 削除・再生成されるファイル                    |
| ------- | --------------------------------------------- |
| `bg`    | 背景画像 + コンポジット + セグメント動画      |
| `audio` | TTS音声 + タイムスタンプJSON + セグメント動画 |
| `sub`   | 字幕ASS + マージ済み動画（compose のみ実行）  |
| (なし)  | 上記すべて                                    |

## ディレクトリ構成

```
tensyoku_movie_generator/
├── main.py                   # エントリーポイント
├── scene_gen.py              # 背景生成 + TTS + Kling V3動画生成（並列実行）
├── compositor.py             # ASS字幕合成 + 最終動画合成
├── post_captions_gen.py      # SNS投稿キャプション生成
├── keyword_extractor.py      # 日本語キーワード抽出（カタカナ/漢字）
├── screenplay_validator.py   # jsonschema ベースの台本バリデータ
├── imagen_client.py          # Gemini画像API
├── fal_video_client.py       # fal.ai Kling V3 API（exponential backoff）
├── elevenlabs_client.py      # ElevenLabs TTS API
├── preview_server.py         # Flask Preview UI
├── log_setup.py              # logging 共通セットアップ
├── config.py                 # プロジェクト設定
├── views/                    # Flask HTMLテンプレート
├── screenplays/              # 台本JSON（手動作成）
├── drafts/                   # 台本の下書き（1動画1ディレクトリ＋3ファイル）/ リサーチ素材（.gitignore 対象）
├── characters/               # 参照キャラクター画像（PNG、任意）
├── tests/                    # pytest テスト
├── post_captions/            # 生成されたSNS投稿キャプション
├── output/                   # 生成動画
├── reports/                  # 生成レポート / Redoログ / ジョブ永続化 / コスト履歴
└── temp/                     # タイムスタンプ別一時ファイル (metadata.json 含む)
```
