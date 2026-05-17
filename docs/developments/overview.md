# Short Movie Generator — システム全体像

最終更新: 2026-05-10

本ドキュメントは「新規セッション / 新規メンバーがこれ 1 ファイル読めば全体像を把握できる」状態を狙った統合 reference。各セクションは要点に絞り、深い詳細は末尾の「詳細」リンクで個別 doc に委譲する。重複は最小限にし、ここを SSOT にしない (= 個別 doc が SSOT、本書は索引 + 全体俯瞰)。

---

## 0. ドキュメントマップ

| 観点                                   | 詳細 doc                                                      |
| -------------------------------------- | ------------------------------------------------------------- |
| 運用ルール / 台本仕様 / コマンド一覧   | `CLAUDE.md`                                                   |
| 静的構造 (レイヤ / 依存方向 / API)     | `docs/developments/architecture.md`                           |
| ドメイン用語辞書                       | `docs/developments/ubiquitous-language.md`                    |
| コーディング規約 (Python / TypeScript) | `docs/developments/coding-rules.md`                           |
| テスト戦略 / 観点 / factory            | `docs/developments/testing.md`                                |
| Claude Code 運用                       | `docs/developments/claude-code-usage.md`                      |
| モデル選定 / コスト / プロンプト       | `docs/architecture-decisions.md`                              |
| 抽象台本 + compose 設計                | `docs/abstract-screenplay-design.md`                          |
| 動画戦略 / コンテンツ軸                | `docs/content-strategy.md`                                    |
| Layer 1-3 図解 (現状記述)              | `docs/plannings/2026-05-10_parts-and-composition-overview.md` |
| Layer 1-3 設計 (authoritative)         | `docs/plannings/2026-05-10_compositional-architecture.md`     |
| analyze pipeline 準拠アップデート      | `docs/plannings/2026-05-10_analyze-pipeline-conformance.md`   |
| その他フロー文書                       | `docs/plannings/YYYY-MM-DD_*.md`                              |

---

## 1. プロジェクト概要

**Short Movie Generator** は、参考動画から `scripts/analyze_video.py` で逆算生成した台本 (= 抽象台本) を入力に、**YouTube Shorts / Instagram Reels / TikTok 用の縦型ショート動画 (1080×1920, 60fps, 日本語特化)** を生成する自動化ツール。screenplay を手書きで起こす UI / API は無く、analyze pipeline が現状の唯一の作成経路 (= analyze 出力 `screenplays/auto_<sha>.json` を `staged_pipeline.load_template` で project snapshot 化し、`screenplay_validator` が Stage 1 と全 UI 編集経路で検証する。両者は live コードで legacy ではない)。

### 1.1 設計の核 (= 4 つの分離原則)

| 原則                                   | 内容                                                                                                                                                                                       |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **段階的ゲート方式 (= 8 stages)**      | 通常 CLI (`main.py`) / preview UI は 1 起動 = 1 stage で停止し UI 承認で次に進む。フルオートは `scripts/auto_loop.py` (= 参考動画 URL 起点 + 予算 cap + Stage 8 human gate) のみが正規経路 |
| **Production Pipeline ↔ Stage 6 合成** | 重い (= AI 課金) 素材製造 (Stage 1-5) と、ffmpeg による字幕焼き込み合成 (Stage 6) を完全分離                                                                                               |
| **2 SSOT (= キャラ + ロケ)**           | screenplay は参照だけ持ち、本体は `characters/<base>/` と `locations/<id>.json` に集約                                                                                                     |
| **Template / Project Snapshot 分離**   | `screenplays/<name>.json` (template、git 追跡) と `temp/<TS>/screenplay.json` (作業 immutable copy)                                                                                        |

### 1.2 守るべき最重要ルール

- **AI 課金が増える方向の変更は禁止** (= 動画再生成 / 背景再生成 / TTS 再生成 / リップシンクは課金。字幕修正に動画は再生成しない)
- **すべての台本に汎用的に対応** (= 特定台本にしか通用しないハードコード禁止)
- **指示の範囲を超えない** (= 「字幕を修正して」と言われたら字幕だけ。台本テキスト・シーン構成・動画は触らない)
- **台本は人間が作成する** (= 自動生成・ブレストはスコープ外。analyze pipeline は参考動画から逆算する例外)

詳細: `CLAUDE.md` 「最重要ルール」

---

## 2. クイックスタート

```bash
# サーバ起動 (= 開発時)
python3 preview_server.py             # http://127.0.0.1:5555 (バックエンド)
cd frontend && npm run dev            # http://localhost:5173 (Vite dev server)

# CLI で 1 stage 実行
python3 main.py <台本名>              # 新規 TS 発行 + Stage 1 実行
python3 main.py <台本名> --resume <TS> # 既存 TS の次 stage 実行 (Stage 1-6 まで)

# 参考動画から抽象台本を生成
python3 scripts/analyze_video.py path/to/reference.mov

# Stage 7 (取込) / Stage 8 (公開)
python3 main.py --resume <TS> --list-finals
python3 main.py --resume <TS> --canonical 142233.mp4
python3 main.py --resume <TS> --publish youtube --privacy unlisted
```

詳細: `CLAUDE.md` 「コマンド一覧」

---

## 3. 8-Stage ゲート方式

```
[1.台本] → [2.TTS] → [3.背景] → [4.Kling] → [5.scene 合成] → [6.字幕 = pipeline raw 出力]
                                                                           ↓
                                                  [7.取込 raw → canonical] → [8.公開]
```

### 3.1 Stage 別の役割と成果物

| Stage          | 役割                     | 主要 API / ツール                               | アーティファクト                                                      |
| -------------- | ------------------------ | ----------------------------------------------- | --------------------------------------------------------------------- |
| **1. script**  | 検証 + メタ書き出し      | `screenplay_validator` (純ローカル)             | `metadata.json` + project snapshot 確定                               |
| **2. tts**     | screenplay 全体を 1-shot | ElevenLabs `eleven_v3` (`with-timestamps`)      | `tmp/tts_<S>_<L>.mp3` + char-level alignment                          |
| **3. bg**      | scene 別背景画像         | Google Imagen `gemini-3-pro-image-preview`      | `tmp/bg_<S>.png`                                                      |
| **4. kling**   | I2V アニメーション       | fal.ai Kling V3 Standard                        | `tmp/kling_<S>.mp4` + `tmp/scene_<S>.trim.mp4`                        |
| **5. scene**   | 音声重ね + lipsync       | FFmpeg + Sync.so `lipsync-2`                    | `tmp/scene_<S>.mp4`                                                   |
| **6. overlay** | 字幕焼き込み + caption   | FFmpeg/libass + Claude Haiku                    | `output/reels_<TS>.mp4` (= pipeline raw) + `post_captions/<title>.md` |
| **7. final**   | raw を canonical 化      | (純ローカル、外部 API なし)                     | `temp/<TS>/final/<HHMMSS>.mp4` + `metadata.json.final_versions[]`     |
| **8. publish** | SNS 公開                 | YouTube Data API / Graph API stub / Display API | `published_posts[]` + `analytics.posts`                               |

### 3.2 承認サイクル

- 各 stage の成果物は `temp/<TS>/tmp/` に保存され、進捗は `tmp-progress.json` で管理される
- `progress_store.mark_approved("<stage>")` で次 stage が解除される
- 個別シーン再生成時は当該 stage + 後続 stage (kling/scene/overlay) の承認も連鎖リセットされる
- `artifact_integrity` で各成果物を検証。整合性 NG は自動削除 + 再生成 (= `ARTIFACT_INTEGRITY_AUTO_DELETE=1`)

### 3.3 自動境界

- **Stage 1-6**: パイプラインが自動で生成し、UI 承認で次に進む完全自動経路
- **Stage 7**: `scripts/auto_loop.py` 内 `_import_raw_as_final()` 経由のみで進む内部経路 (= manual main.py からは進行しない)
- **Stage 8**: ユーザの publish コマンドが起点。YouTube は完全自動、IG/TikTok は半自動 (= caption をクリップボードへ + アプリ起動)

詳細: `docs/developments/architecture.md` §1, §3

---

## 4. レイヤ構造

```
┌────────────────────────────────────────────────────────────┐
│ エントリ層                                                 │
│  main.py / preview_server.py / scripts/auto_loop.py        │
│  scripts/analyze_video.py / scripts/{ingest,fetch}_*.py    │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│ オーケストレータ層                                         │
│  staged_pipeline.py    (= stage dispatcher)                │
│  progress_store.py     (= gate 制御)                       │
│  preflight.py / screenplay_validator.py                    │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│ 生成・編集層 (stage 実装)                                  │
│  scene_gen.py          (= BG / Kling / scene 合成)         │
│  compositor.py         (= Stage 6 ffmpeg 字幕焼き込み)     │
│  clip_library.py       (= 永続クリップキャッシュ)          │
│  audio_dynamics / furigana_store / post_captions_gen       │
│  final_import/         (= Stage 7)                         │
│  platform_clients/     (= Stage 8)                         │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│ 外部 API クライアント層                                    │
│  elevenlabs_client / imagen_client / fal_video_client      │
│  fal_runner / lipsync_client / whisper_client              │
│  video_analyzer (Claude Opus 4.7)                          │
│  gemini_dialogue_rewriter (Gemini 2.5 Pro)                 │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│ ユーティリティ・基盤層                                     │
│  io_utils / log_setup / config / artifact_integrity        │
│  bg_cache / kling_cache / cache/ / cost_tracking/          │
└────────────────────────────────────────────────────────────┘

並走する独立トラック (= メイン経路から orthogonal):
  analyze/    参考動画 → 抽象台本 (Claude + Whisper + librosa + Gemini rewrite)
  analytics/  SQLite DB と auto-tag (Claude Haiku)
```

### 依存方向の規則

- 上層は下層に依存可。**下層は上層を知らない** (= 逆方向依存禁止)
- 同層間の依存は最小限。例えば `scene_gen.py` と `compositor.py` は直接互いを呼ばず、`staged_pipeline.py` が両方を呼ぶ
- 外部 API クライアント層は副作用の入口。テストではここをモックする
- `analyze/` と `analytics/` は orthogonal。互いを知らず、メイン生成パイプラインからも独立

詳細: `docs/developments/architecture.md` §2

---

## 5. データモデル

### 5.1 2 SSOT 分離 (= キャラ + ロケ)

VideoStyle は廃止済み。各 scene が `animation_prompt` / `location_ref` / `character_refs` を直接持つ。

| SSOT               | 場所                                | 内容                                                                |
| ------------------ | ----------------------------------- | ------------------------------------------------------------------- |
| キャラエンティティ | `characters/<base>/`                | `voice.json` + 衣装バリアント PNG                                   |
| ロケ集             | `locations/<id>.json` + preview.png | 1 ロケ = decor + lighting + color_palette + props + camera_distance |

```
characters/
  f1/                      ← 被写体 ID (= 顔・体型・髪型が同じ人物)
    voice.json             ← voice メタ (= base 単位で 1 つ)
    base.png               ← 衣装サフィックス無しの参照画像
    office.png             ← `f1__office` で参照される衣装バリアント
    casual.png             ← `f1__casual`
```

screenplay の `character_refs` は **解決済み ref** (例: `f1__office` = `<base>__<wardrobe>`)。衣装無しは `<base>` 単独。

ロケ詳細は `background_prompt` 先頭にラベル付きで自動注入される (= "location decor: ..." 等)。scene ごとは被写体の動作・表情のみ書く運用。

### 5.2 Template / Project Snapshot 分離

| 種別                 | パス                        | git    | 用途                                                                                                                                                                                                                       |
| -------------------- | --------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **template**         | `screenplays/<name>.json`   | 追跡   | 新規 project 作成時の素材。現状は **analyze pipeline 出力** (= `auto_<sha>.json`) のみが生成される。`compose` (= `PUT /api/projects/<ts>/abstract`) の結果は project snapshot を更新するだけで template には書き出されない |
| **project snapshot** | `temp/<TS>/screenplay.json` | ignore | template から copy された **immutable な作業コピー**。Stage 1〜6 のすべて、UI の line/scene patch、再合成は **このファイルだけ** を読み書き                                                                                |

**ポイント**: project 作成時に template から snapshot がコピーされ、以後 template が外部で書き換わっても進行中 project は影響を受けない。

| 関数 (`staged_pipeline`)               | 対象                        | 用途                                                      |
| -------------------------------------- | --------------------------- | --------------------------------------------------------- |
| `load_template(name)`                  | `screenplays/<name>.json`   | 新規 project 作成時のロードのみ                           |
| `load_project_screenplay(ts_path)`     | `temp/<TS>/screenplay.json` | 後 stage / UI / 再合成 — **読み取りはすべてこれ**         |
| `save_project_screenplay(ts_path, sp)` | `temp/<TS>/screenplay.json` | **書き込みもすべてこれ**。metadata.json の sha も同時更新 |

旧 `save_screenplay(name, sp)` と `screenplays/drafts/` ディレクトリは廃止 (= 移行済み)。

### 5.3 永続化対象

```
[git 追跡]
  screenplays/<name>.json       ← 台本テンプレート
  characters/<base>/*           ← キャラ参照画像 + voice.json
  locations/<id>.json + preview ← ロケ詳細
  config.py / config/part_registry/visual_intents.yaml
  data/pricebook.json           ← 単価カタログ (運用者管理)

[git ignore / 動的生成]
  temp/<TS>/                    ← 1 動画分のプロジェクト
    screenplay.json             ← snapshot
    metadata.json               ← sha / final_versions[] / published_posts[]
    tmp-progress.json           ← stage gate 状態
    tmp/*                       ← 中間アーティファクト
    final/*                     ← Stage 7 取込済み (複数バージョン)
  output/reels_<TS>.mp4         ← Stage 6 で書き出される pipeline raw
  post_captions/<title>.md      ← SNS キャプション
  cache/clips/<entry_id>/       ← Layer 1 永続キャッシュ
  data/analytics.db             ← SQLite (screenplays / videos / posts / post_metrics)
  data/cost_records.jsonl       ← analyze pipeline のコスト履歴
```

### 5.4 Screenplay Schema (要約)

```json
{
  "caption": "知らないと損する3つのコツ\n\n#tips #ライフハック",
  "scenes": [
    {
      "identity": {
        "character_refs": ["f1__office"],
        "location_ref": "home_office",
        "start_emotion": "中立",
        "camera_distance": "medium-close"
      },
      "annotation": {
        "visual_intent_id": "talking_head_calm",
        "duration_bucket": 5,
        "motion_intensity": "low"
      },
      "location_ref": "home_office",
      "background_prompt": "...",
      "animation_prompt": "...",
      "character_refs": ["f1__office"],
      "characters": [{ "name": "f1__office" }],
      "lipsync": true,
      "lines": [
        {
          "text": "やばいやばい",
          "emotion": "焦り",
          "delivery": "早口で小声",
          "audio_tags": ["whispers"],
          "pronunciation_hints": { "IT": "アイティー" }
        }
      ]
    }
  ]
}
```

- **identity / annotation** は #149-#151 で導入された clip_library cache 鍵 (詳細は §6)
- `duration` / `start` / `end` は **Stage 2 (TTS) が実音声長から書き込む派生値**。Stage 1 抽象台本には書かない (= `tts_meta.json` に分離)
- `text` の ASCII の `,` `.` は validator で reject (= 全角句読点に矯正)

詳細: `CLAUDE.md` 「台本JSONの仕様」、`docs/abstract-screenplay-design.md`

---

## 6. Clip Library (= 永続クリップ cache)

scene の **identity** をキーに、過去に Imagen + Kling で生成した bg/動画クリップを再利用する仕組み。

| 項目           | 内容                                                                                                                                                |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 保存先         | `cache/clips/<entry_id>/` (= `bg.png` + `kling_clean.mp4` + `meta.json`)                                                                            |
| **identity**   | `(character_refs, location_ref, start_emotion, camera_distance)` の 4 軸。これが pool を決める                                                      |
| **annotation** | `visual_intent_id` / `duration_bucket` / `motion_intensity`。pool 内の variant rank に使う (= soft signal、完全一致 +3 / 互換 +1.5 / 部分一致 +0.5) |
| variant 選択   | `seed = sha256(ts + scene_idx)` で決定論的。同じ screenplay の rebuild で同じ動画が出る                                                             |
| miss 動作      | cold path = Imagen + Kling 課金 → `register_clip_entry(status: pending_review)` で pool に登録                                                      |
| wire 状態      | `CLIP_LIBRARY_ENABLED=1` で wire 完了 (= main 着地済み)                                                                                             |

**重要不変条件**: identity 4 軸が一致する 2 つの scene は **必ず同じ entry pool に hit する**。`lines[*]` / emotion arc / wpm 等の per-line 情報は cache key に **入らない**。

詳細: `docs/plannings/2026-05-10_clip-library-architecture.md` を参照。

---

## 7. Production Pipeline 詳細 (Stage 1-5)

### 7.1 Stage 1: script

- `screenplay_validator.py` で検証 (= ASCII `,`/`.` reject、必須フィールド確認、`visual_intent_id` を `config/part_registry/visual_intents.yaml` と突合)
- 新規 project なら template から snapshot へコピー、`metadata.json` に sha を書く
- analyze 経由 project (= `metadata.json.analyze_job_id` 有り) は Stage 1 ページ上部に「素材編集」セクション (= 参考動画 read-only / 抽象台本 / 話者マッピング) が出る

### 7.2 Stage 2: tts

- `generate_screenplay_tts_one_shot()` が dispatcher として 2 経路を分岐 (= 2026-05-17 `docs/plannings/2026-05-17_per-character-tts.md`):
  - **single-voice** (= 0/1 speaker): screenplay 全体を 1 ElevenLabs API call で生成。char-level timestamps + silence-detect snap で line 境界決定
  - **per-character** (= 2+ speakers): speaker ごとに `characters/<base>/voice.json.voice_id` で並列フル生成 (= ThreadPool, MAX 4) → 各 line をその speaker の voice 音声から切出 → merged `tts_full.mp3` に concat
- voice_id 解決: `characters/<base>/voice.json.voice_id` → `config.ELEVENLABS_VOICE_ID` の 2 段 fallback
- per-line の表現切替は **inline tag だけ** (= `audio_tags[]`, `emotion`, `delivery`)
  - `emotion` (例: `驚き`, `焦り`) → `config.EMOTION_AUDIO_TAGS` 経由で `[surprised]` 等を `line.text` 先頭に自動挿入
  - `audio_tags[]` (例: `["whispers"]`, `["shouts"]`) → 直接挿入
  - `delivery` (= 自然言語の話し方) → `DELIVERY_TAG_ENABLED=True` 時に `[delivery] text` 形式で送信
- `pronunciation_hints` で TTS 送信前のテキスト置換 (例: `{"IT": "アイティー"}`)
- 出力: `tmp/tts_<S>_<L>.mp3` 群 + `audio_<S>.m4a` + `tts_full.mp3` + `tts_meta.json` (= duration / start / end の派生値)
- per-voice intermediate: `tts_full.<base>.mp3` + `.json` + `.text_meta.json` (= multi-voice 時のみ、speaker 別 cache)
- 課金: single-voice = 1×、per-character = N× (= speaker 数倍。短尺 30 秒 2 speaker なら ~\$0.08)

### 7.3 Stage 3: bg

- Google Imagen `gemini-3-pro-image-preview` で scene ごとに `bg_<S>.png`
- アスペクト比 9:16 (= 動画と同じ縦長)
- `background_prompt` 先頭にロケ詳細 (= decor / lighting / color_palette / props / camera_distance) が自動注入される
- character 参照画像 (= `characters/<base>/<wardrobe>.png`) を image-to-image で食わせて衣装一貫性を担保
- `CLIP_LIBRARY_ENABLED=1` 時は scene の identity が一致する pool 内 variant を hit させる (= AI 課金 0)

### 7.4 Stage 4: kling

- fal.ai Kling V3 Standard で I2V (= image-to-video) アニメーション生成
- 入力: Stage 3 の `bg_<S>.png` + `animation_prompt` (= 英語推奨、シーン全体の動きを 1 文)
- emotion → Kling motion addon (= `config.EMOTION_MOTION_ADDONS`) が animation_prompt に追加される
- `duration` は `duration_bucket` (= 5 / 10) で離散化 (= cache hit 率向上のため)
- 出力: `tmp/kling_<S>.mp4` (= raw) + `tmp/scene_<S>.trim.mp4` (= 動作完了点で trim)
- Layer 1 hit 時は cache から `kling_clean.mp4` を copy (= AI 課金 0)

### 7.5 Stage 5: scene

- FFmpeg で kling 動画に Stage 2 の音声を重ね、Sync.so でリップシンク合成
- Sync.so 公式 API (`/v2/generate` multipart + polling)、モデルは `lipsync-2` (既定)
  - `SYNCSO_LIPSYNC_MODEL` で `lipsync-2-pro` (= 高品質) / `lipsync-1.9.0-beta` (= 高速) / `react-1` / `sync-3` に切替可能
  - multipart 上限 1 ファイル 20MB
- 出力: `tmp/scene_<S>.mp4` (= 完成 lipsync 済みシーン動画)

詳細: `docs/architecture-decisions.md` 「3. モデル・API選定」、`CLAUDE.md` 「リップシンクプロバイダー」

---

## 8. Stage 6 (字幕焼き込み) 詳細

### 8.1 字幕の手動チャンク制御

各 line に `subtitles: [{text, start?, end?}]` を指定すると、自動分割 (`_split_into_chunks`) を **完全にスキップ** し、ここに書かれた通りのチャンクで字幕を焼き込む。

| chunk の time   | 動作                                                                                             |
| --------------- | ------------------------------------------------------------------------------------------------ |
| 両方省略 (auto) | line.start - line.end の中で、前後の固定境界 (= 手打ち time or line 端) との間を文字数比例で配分 |
| 両方指定        | その値を絶対の境界として使用 (= 隣接 auto chunks のアンカー)                                     |

`compositor._resolve_subtitle_timings` がアンカー方式で混在ケースを解決する (= 文字数 0 の auto chunks は均等割にフォールバック)。

UI (`StageOverlay.tsx`) では「手動に切替」「分割」「+ チャンク追加」「× 削除」、動画プレイヤーの再生位置をスナップする「⏱→start」「⏱→end」ボタン、「auto に戻す」で柔軟に編集できる。

### 8.2 オーバーレイのスコープ

最終動画には **字幕 (lines[].text) のみ** を焼き込む。タイトル帯/時刻表示/ラベル/インサート画像/ポップアップなどのオーバーレイは廃止。`scenes[].label` は動画には描画されず、シーン識別のメタ情報として UI 表示と LLM 補助入力に使われる。

### 8.3 Caption 生成

Stage 6 完了時に Claude Haiku で SNS 投稿用キャプション (= ハッシュタグ込み) を `post_captions/<title>.md` に書き出す。pipeline raw `output/reels_<TS>.mp4` も同時に出力される。

詳細: `CLAUDE.md` 「オーバーレイ」

---

## 9. Stage 7 (取込) + Stage 8 (公開) + Analytics

### 9.1 Stage 7: final import

`scripts/auto_loop.py:_import_raw_as_final()` が pipeline raw を `final_import.import_final(ts, src)` 経由で `temp/<TS>/final/<HHMMSS>.mp4` に取り込み、`metadata.json.final_versions[]` に登録する。これが **唯一の取込経路** (= manual main.py からは進行しない)。

複数バージョンを保管できる。`is_canonical` フラグで「analytics / publish の正本」を管理し、UI または CLI (`--canonical <FILENAME>`) で切替可能。

```bash
python3 main.py --resume <TS> --list-finals
python3 main.py --resume <TS> --canonical 142233.mp4
```

### 9.2 Stage 8: publish

| platform            | 自動化                                           | 必要 env                                                        |
| ------------------- | ------------------------------------------------ | --------------------------------------------------------------- |
| **YouTube Shorts**  | 完全自動 (Data API resumable upload)             | `YOUTUBE_OAUTH_CLIENT_ID` / `_CLIENT_SECRET` / `_REFRESH_TOKEN` |
| **Instagram Reels** | 半自動 (caption をクリップボードへ + アプリ起動) | (Phase 1 不要。Graph API は `INSTAGRAM_*` で stub 済)           |
| **TikTok**          | 半自動 + CSV 取込                                | (Phase 1 不要。Display API は `TIKTOK_*` で stub 済)            |

YouTube は upload 成功時に `analytics.posts` に自動登録。IG/TikTok は半自動なのでアップロード後にユーザが URL を `register_post.py` で投入する。

```bash
python3 main.py --resume <TS> --publish youtube --privacy unlisted
python3 main.py --resume <TS> --publish instagram     # 半自動
python3 scripts/ingest_tiktok_csv.py path/to/video_performance.csv  # TikTok 暫定経路
```

### 9.3 Analytics

SQLite (`data/analytics.db`) で台本 × 動画 × 投稿 × 時系列メトリクスを管理する。

```
ingest_screenplay.py    # 台本登録 + Claude Haiku auto-tag (hook_type/tone/dominant_emotion/theme/character_archetype)
ingest_video.py         # 動画登録 (canonical があれば自動でそれを output_path に)
register_post.py        # 投稿 URL 登録 (YouTube は publish 時に自動登録済)
fetch_metrics.py        # 最新メトリクス取得 (YouTube 完全対応、IG/TikTok は env 設定後)
streamlit run scripts/dashboard.py    # ダッシュボード
```

| テーブル        | 説明                                                                                |
| --------------- | ----------------------------------------------------------------------------------- |
| `screenplays`   | 台本 + 自動タグ (hook_type / tone / dominant_emotion / theme / character_archetype) |
| `videos`        | 生成動画、台本 ID で紐付け                                                          |
| `posts`         | 投稿 (YouTube / Instagram / TikTok)、video_id で紐付け                              |
| `post_metrics`  | 時系列メトリクス、post_id で紐付け                                                  |
| `v_performance` | 横断ビュー (= 台本 × 動画 × 投稿 × 最新メトリクス)                                  |

詳細: `CLAUDE.md` 「分析基盤（Analytics）」

---

## 10. Analyze Pipeline (= 参考動画 → 抽象台本)

`scripts/analyze_video.py` がメイン経路。**メイン生成パイプラインから orthogonal** で、参考動画 (.mov/.mp4) から抽象台本 JSON を逆算生成する。

### 10.1 技術スタック

| 工程           | 技術                                                                                                        |
| -------------- | ----------------------------------------------------------------------------------------------------------- |
| フレーム抽出   | ffmpeg、0.5 秒刻み (`--fps 2.0` 既定)                                                                       |
| 音声書き起こし | OpenAI Whisper (= word-level)。`OPENAI_API_KEY` 無ければ `faster-whisper` ローカル                          |
| 音響特徴       | `librosa` で各 phrase の pitch / rms / wpm 抽出                                                             |
| 統合推論       | Claude Opus 4.7 (1M context) に全素材を渡し、抽象台本を出力                                                 |
| コスト算定     | `data/cost_records.jsonl` median から動的 (履歴 < 3 件は「履歴不足」)。単価カタログは `data/pricebook.json` |

### 10.2 抽象台本 + compose

analyze pipeline は **抽象台本** (= 構成・セリフ・感情・匿名 `speaker_N` のみ、ビジュアル要素なし) を出力する。完全 screenplay は **compose 段階** で構築される:

```
抽象台本 (= speaker_1, speaker_2, ...)
  + 話者マッピング (= speaker_N → 実 character ref)
  + scene 個別フィールド (= location_ref, animation_style, character_selection)
                ↓
        analyze/compose.py
                ↓
        完全 screenplay (= identity + annotation 含む)
```

UI の Stage 1 で話者マッピングを 1 回設定するだけで、各シーンの登場人物と各 line の voice_overrides が自動推論される。

### 10.3 直近の準拠アップデート (= PR #149-#151)

`docs/plannings/2026-05-10_analyze-pipeline-conformance.md` の 3 step プランが完了:

1. **#149 annotation 注入** — `intent_resolver` を analyze pipeline に wire し、Claude が `visual_intent_id` / `duration_bucket` / `motion_intensity` を出力
2. **#150 identity 派生 (= compose で生成)** — `compose` が `(character_refs, location_ref, start_emotion, camera_distance)` の 4 軸 identity を生成
3. **#151 error_code 統一** — analyze 系 endpoint の error response を `{error_code, message, ...}` SSOT に揃えた

これで Layer 1 cache hit が **構造的に発動する** 状態 (= 設計が掲げた warm 時 per-screenplay 課金が **TTS + Sync.so のみ** に縮退する経路) が開通した。

詳細: `docs/abstract-screenplay-design.md`、`docs/plannings/2026-05-10_analyze-pipeline-conformance.md`

---

## 11. 認証 / 環境変数

| 区分             | env                                                             | 必須/任意         | 用途                                                        |
| ---------------- | --------------------------------------------------------------- | ----------------- | ----------------------------------------------------------- |
| 生成パイプライン | `ANTHROPIC_API_KEY`                                             | 必須              | analyze / auto-tag / caption 生成                           |
|                  | `ELEVENLABS_API_KEY`                                            | 必須              | TTS (Stage 2)                                               |
|                  | `GOOGLE_API_KEY`                                                | 必須              | Imagen 背景生成 (Stage 3)                                   |
|                  | `FAL_KEY`                                                       | 必須              | Kling V3 (Stage 4)                                          |
|                  | `SYNC_API_KEY`                                                  | 必須              | Sync.so lipsync (Stage 5)                                   |
|                  | `OPENAI_API_KEY`                                                | 任意              | Whisper (analyze)。無ければ `faster-whisper` ローカル       |
| 公開             | `YOUTUBE_OAUTH_CLIENT_ID` / `_CLIENT_SECRET` / `_REFRESH_TOKEN` | YouTube 公開時    | refresh token で headless 上げ                              |
|                  | `YOUTUBE_API_KEY`                                               | metrics 取得時    | 公開統計                                                    |
|                  | `INSTAGRAM_ACCESS_TOKEN` / `INSTAGRAM_BUSINESS_ID`              | IG metrics 時     | Graph API                                                   |
|                  | `TIKTOK_ACCESS_TOKEN` / `TIKTOK_OPEN_ID`                        | TikTok metrics 時 | Display API                                                 |
| analytics        | `ANALYTICS_DB_PATH`                                             | 任意              | 既定 `data/analytics.db`                                    |
| 観測             | `LOG_LEVEL` / `LOG_FILE`                                        | 任意              | logging モジュール                                          |
| 運用 gate        | `ARTIFACT_INTEGRITY_AUTO_DELETE`                                | 任意              | 整合性 NG の自動削除                                        |
|                  | `CLIP_LIBRARY_ENABLED`                                          | 任意              | 永続クリップキャッシュ (= 1 で wire)                        |
|                  | `DISABLE_AUTO_LOOP`                                             | 任意              | `scripts/auto_loop.py` の kill-switch (= cron 経路の即停止) |
| Tailscale 経路   | `FLASK_HOST` / `PREVIEW_AUTH_TOKEN` / `VITE_PREVIEW_TOKEN`      | 任意              | モバイル等から preview_server を触る場合                    |

詳細: `docs/developments/architecture.md` §6, §8.1

---

## 12. 実行モード

| モード        | 起動                                                              | 用途                                |
| ------------- | ----------------------------------------------------------------- | ----------------------------------- |
| 単発 (CLI)    | `python3 main.py <名前>` / `python3 main.py <名前> --resume <TS>` | 1 stage ずつ手動実行                |
| プレビュー UI | `python3 preview_server.py` + `cd frontend && npm run dev`        | 承認サイクル + 可視化               |
| analyze       | `python3 scripts/analyze_video.py <参考動画>`                     | 参考動画 → 抽象台本 JSON            |
| analytics     | `python3 scripts/{ingest,register_post,fetch_metrics}.py`         | DB 取込 / 投稿登録 / メトリクス取得 |
| dashboard     | `streamlit run scripts/dashboard.py`                              | 横断ビュー閲覧                      |
| フルオート    | `python3 scripts/auto_loop.py` (= cron)                           | Stage 7 取込 + URL 起点フルラン     |

**本番デプロイは無い** (= ローカル実行のみ)。Tailscale 経由でモバイルから preview_server を触る運用想定で、`PREVIEW_AUTH_TOKEN` で第二防衛を張る。

---

## 13. 不変条件 (= これが崩れたら危険信号)

1. **AI 課金が増える方向の変更は禁止**: 字幕修正で動画再生成しない。参照画像差替え (= identity hash 変化) のみが Stage 3+4 cold path を引き起こす
2. **Clip Library cache 識別性**: identity 4 軸 `(character_refs, location_ref, start_emotion, camera_distance)` が一致する 2 つの scene は **必ず同じ entry pool に hit する**
3. **timing 計算は Python SSOT**: subtitle chunk の絶対秒は `compositor.py` で一括解決
4. **screenplay の編集は project snapshot のみ**: template (`screenplays/<name>.json`) は project 作成後に触らない (= 進行中 project 不変の担保)
5. **段階的ゲートを破らない**: 承認なしに次 stage に進む経路を作らない
6. **指示の範囲を超えない**: 「字幕を修正して」と言われたら字幕だけ。台本テキスト・シーン構成・動画は触らない

---

## 14. 直近の主な変化 (= 2026-05-17 時点)

1. **演出パーツ (scene_parts / global_parts) + Remotion backend を全廃** (= `2026-05-17_drop-remotion-and-parts.md`): Stage 6 は `compositor.py` (ffmpeg / libass) 単線に戻し、screenplay スキーマも `caption + scenes` のみのフラット構造に。`visual_intents` (= Clip Library の cache key) は維持
2. **per-character TTS** (= `2026-05-17_per-character-tts.md`): Stage 2 が speaker 数で分岐し、複数話者なら N 並列フル生成 + cut & merge で speaker 別 voice を割当てる。各キャラの voice_id は `characters/<base>/voice.json` で管理
3. **casting decouple** (= `2026-05-17_decouple-casting-from-reference.md`): 参考動画の登場人物に寄せず、catalog の alphabetical 順に割当てる。Stage 1 UI で人間が自由に選び直す前提
4. **dialogue rewrite phase** (= `2026-05-17_gemini-dialogue-rewrite.md`): Claude inference 直後に Gemini 2.5 Pro で line.text + caption を「同じ意味で独自の言い回し」に書き換える (= 翻案権配慮)。失敗時 graceful fallback、`ANALYZE_DIALOGUE_REWRITE_ENABLED=0` で kill-switch
5. **speaker mapping schema 撤廃** (= `2026-05-17_drop-speaker-mapping-schema.md`): `speaker_to_ref` / `speaker_profiles` / raw `speaker_N` を全廃。line.speaker は analyze 時点で resolved id (`f1__office` 等) を直書き。Stage 1 UI も SpeakerMappingSection を撤去し per-line picker に bulk-apply 統合。compose の speaker resolution step も dead code 撤去。abstract 設計原則の「speaker 周りの hypothetical な拡張余地」を YAGNI 解消
6. **Clip Library が動く**: `CLIP_LIBRARY_ENABLED=1` で `staged_pipeline.run_bg` から `satisfy_scenes_from_library` が動き、`run_scene` 直前で `register_cold_path_clips` が動く。同条件 scene の 2 回目以降 Imagen + Kling 課金 0
7. **analyze pipeline 設計準拠完了** (PR #149-#151): identity 派生 + annotation 注入 + error_code 統一。これで Clip Library cache hit が **構造的に発動する** 状態に
8. **抽象台本 + compose 合成**: 参考動画から作る台本もビジュアル決定を分離 (= 構成・セリフ・感情だけ抽出、ビジュアルは scene 個別 + 話者マッピングで後段注入)

設計の方向性は **「自由記述で AI に毎回作らせる」 → 「enum 化された pool から決定論的に選ぶ」** への転換が中核で、これが完了しつつある段階。

---

## 15. 実装ステータス サマリ

| 領域                        | 状態                                                     |
| --------------------------- | -------------------------------------------------------- |
| Stage 1-6 Production        | ✅ 完成                                                  |
| Stage 7 取込                | ✅ `scripts/auto_loop.py` 経路で wire                    |
| Stage 8 publish (YouTube)   | ✅ 完全自動                                              |
| Stage 8 publish (IG/TikTok) | △ Phase 1 半自動。Graph API / Display API は stub 済     |
| Clip Library                | ✅ wire 完了 (= `CLIP_LIBRARY_ENABLED=1`)                |
| analyze pipeline 準拠       | ✅ identity / annotation / error_code すべて完了         |
| analytics                   | ✅ YouTube 完全対応。IG/TikTok は env 設定後             |
| auto_loop フルオート        | ✅ cron 経路で動作。`DISABLE_AUTO_LOOP=1` で kill-switch |

---

## 16. 関連ドキュメント (再掲)

### 静的設計 (= `docs/developments/`)

- `architecture.md` — レイヤ・依存方向・データフロー・Stage × 外部 API マトリクス
- `coding-rules.md` — Python / TypeScript コーディング規約・命名・log・error handling
- `testing.md` — テスト戦略・観点 3 セット・factory・モック規約
- `ubiquitous-language.md` — ドメイン用語辞書
- `claude-code-usage.md` — Claude Code 設定 / hooks / commands / skills / plugins 運用

### ドメイン (= `docs/`)

- `content-strategy.md` — 動画制作の根本戦略
- `architecture-decisions.md` — モデル選定・コスト構造・プロンプト設計の根拠
- `abstract-screenplay-design.md` — 抽象台本生成 + compose 合成の設計

### フロー (= `docs/plannings/`)

- `2026-05-17_drop-remotion-and-parts.md` — 演出パーツ / Remotion 全廃 (authoritative for 現行 Stage 6 構造)
- `2026-05-17_per-character-tts.md` — Stage 2 TTS の per-character voice 化 (= N 並列フル生成 → 切出 → マージ)
- `2026-05-17_decouple-casting-from-reference.md` — casting を参考動画から切り離し (= appearance 突合撤廃、catalog alphabetical 順割当)
- `2026-05-17_gemini-dialogue-rewrite.md` — analyze pipeline に Gemini 2.5 Pro 経由の dialogue rewrite phase を組込 (= 翻案権配慮)
- `2026-05-17_drop-speaker-mapping-schema.md` — `speaker_to_ref` / `speaker_profiles` schema 撤廃 (= line.speaker は resolved id 直書き、dead 抽象化を解消、UI 統合)
- `2026-05-10_analyze-pipeline-conformance.md` — analyze pipeline 準拠アップデート計画 (= PR #149-#151 で完了)
- `2026-05-10_analyze-project-handoff.md` / `2026-05-10_analyze-project-handoff-implementation.md` — analyze→project handoff の Phase A-E (= PR #178-#182 で完了、standalone /analyze 経路廃止)
- `2026-05-10_analytics-pdca-gap-and-remediation.md` — analytics PDCA 3 phase plan (= PR #153 / #158 / #161 で完了)
- `2026-05-10_clip-library-architecture.md` — Clip Library cache の identity match + annotation rank 設計
- `2026-05-10_remove-pending-queue.md` — pending queue 撤去 (= PR #170 / #172)
- `2026-05-10_intent-suggestion-flow.md` — novel intent suggestion review flow
- `2026-05-08_phase-0-implementation.md` 〜 `2026-05-08_phase-4-implementation.md` — 抽象台本立ち上げ Phase 0-4 実装記録
- `2026-05-07_full-automation-*` — フルオートループの判定 + 実装計画
- `2026-05-09_external-edit-import-removal.md` / `2026-05-09_quality-parity-auto-vs-manual.md` — auto_loop 品質パリティ計画

---

最終更新: 2026-05-17
