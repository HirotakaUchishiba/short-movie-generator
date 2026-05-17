# 全体ワークフロー (= 参考動画 → 公開動画までの完全な流れ)

| 項目     | 値                                                               |
| -------- | ---------------------------------------------------------------- |
| 最終更新 | 2026-05-17                                                       |
| 対応     | `docs/developments/overview.md` (= 静的アーキテクチャ) の動的版  |
| 補足     | 本ドキュメントは「何がどの順に走り、何を入出力するか」を記述する |

---

## 1. 1 行サマリ

**参考動画 → Claude 抽出 → Gemini 言い換え → 抽象台本 → ステージ別生成 → SNS 公開** を `python3 main.py` か `scripts/auto_loop.py` で進行。各 stage の成果物は preview UI で承認するまで次に進まない (= 段階的ゲート方式)。

---

## 2. データの 2 層構造 (= SSOT)

| 層                              | パス                                                                                                               | 役割                                                                                          | git    |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- | ------ |
| **template**                    | `screenplays/<name>.json` (= `auto_<sha>.json`)                                                                    | analyze 出力。複数 project の元素材                                                           | 追跡   |
| **project snapshot**            | `temp/<TS>/screenplay.json`                                                                                        | template から作成時にコピーされる immutable 作業コピー。Stage 1〜6・UI 編集・再合成はここだけ | ignore |
| **catalog (= 全 project 共有)** | `characters/<base>/voice.json` + 画像、`locations/<id>.json` + preview、`config/part_registry/visual_intents.yaml` | 全動画で共有される素材                                                                        | 追跡   |
| **派生 metadata**               | `temp/<TS>/metadata.json` / `tmp-progress.json` / `tts_meta.json`                                                  | TS 単位の状態管理 (= 進行 stage / TTS timing / 公開先 etc)                                    | ignore |

---

## 3. 全体フロー (= 1 動画分の完全な流れ)

```
┌─────────────────────────────────────────────────────────────────┐
│ INPUT: 参考動画 (.mov/.mp4)                                     │
└─────────┬───────────────────────────────────────────────────────┘
          ▼
┌─ Stage 0 (analyze) ──────────────────────────────────────────────┐
│ scripts/analyze_video.py                                         │
│   1. ffmpeg で 0.5 秒刻みフレーム抽出                            │
│   2. Whisper で音声 → word-level transcript                      │
│   3. librosa で pitch/rms/wpm 抽出                              │
│   4. Claude Opus 4.7 (1M context) で統合推論                     │
│      → 構成 + セリフ + 感情 + location_ref + camera_distance    │
│      → annotation (visual_intent_id 等)                          │
│      → line.speaker に resolved id 直書き (2026-05-17 改新)      │
│      → featured_characters                                       │
│   5. Gemini 2.5 Pro で line.text + caption を独自言い回しに rewrite│
│      (= 翻案権配慮、PR #204、失敗時 graceful fallback)           │
│   6. screenplay_validator → screenplays/auto_<sha>.json 保存     │
│                                                                  │
│ 所要: 5-10 分 / コスト: ~$0.22 (= Claude $0.20 + Gemini $0.02)  │
└─────────┬────────────────────────────────────────────────────────┘
          ▼
┌─ project 作成 ──────────────────────────────────────────────────┐
│ POST /api/projects (= template → snapshot コピー)                │
│ temp/<TS>/screenplay.json + metadata.json (analyze_job_id 紐付け)│
└─────────┬────────────────────────────────────────────────────────┘
          ▼
┌─ Stage 1 (台本確認/編集) ────────────────────────────────────────┐
│ preview_server + Stage 1 UI                                      │
│   ・台本本文 / 感情 / line.speaker / caption を編集              │
│   ・per-line SpeakerPicker で話者切替 (+ bulk-apply ボタン)      │
│   ・LocationPicker / CameraDistancePicker / animation_style 編集 │
│   ・人間が「OK」ボタン → Stage 2 unlock                          │
│                                                                  │
│ 変更時の挙動: classify_abstract_diff が breaking/safe_only 判定 │
│   - breaking (= text/speaker/scene 変更) → Stage 2-6 承認 reset │
│   - safe_only (= subtitle_y_from_bottom 等) → Stage 6 のみ reset│
└─────────┬────────────────────────────────────────────────────────┘
          ▼
┌─ Stage 2 (TTS) ─────────────────────────────────────────────────┐
│ scene_gen.generate_screenplay_tts_one_shot() = dispatcher        │
│                                                                  │
│  ┌─ unique speakers = 0 or 1 ──┐  ┌─ unique speakers ≥ 2 ────┐ │
│  │ single-voice (= 既存 path)   │  │ per-character (PR #202)   │ │
│  │ 1 ElevenLabs call で全文生成 │  │ N 並列フル生成 → 切出 → │ │
│  │ char-level timestamps 取得   │  │ マージ。各 line は speaker│ │
│  │ silence-detect で line snap  │  │ の voice 音声から切出     │ │
│  └──────────────────────────────┘  └───────────────────────────┘ │
│                                                                  │
│ voice_id 解決: characters/<base>/voice.json.voice_id             │
│              → config.ELEVENLABS_VOICE_ID                       │
│ 出力: tts_full.mp3 / per-line tts_<S>_<L>.mp3 / audio_<S>.m4a   │
│       / merged_preview.m4a / tts_meta.json                       │
│                                                                  │
│ 課金: single = 1x、per-character = N x (= 1 voice = $0.04)      │
└─────────┬────────────────────────────────────────────────────────┘
          ▼
┌─ Stage 3 (背景) ────────────────────────────────────────────────┐
│ scene_gen._generate_background_with_retry()                      │
│   ・Clip Library 先頭 lookup (= identity hash で cache hit なら │
│     Imagen / Kling 共に skip)                                    │
│   ・cache miss なら Imagen (Gemini 3 Pro Image) で生成          │
│     - reference image: characters/<id>/*.png                     │
│     - prompt: location.decor + lighting + props + animation_prompt│
│     - 9:16 縦長 / 1080x1920                                      │
│   ・出力: tmp/bg_<S>.png                                         │
│                                                                  │
│ コスト: $0.04 / image (= cache miss 時のみ)                     │
└─────────┬────────────────────────────────────────────────────────┘
          ▼
┌─ Stage 4 (Kling 動画) ──────────────────────────────────────────┐
│ scene_gen._generate_kling()                                      │
│   ・fal.ai Kling V3 で bg.png + animation_prompt → 動画          │
│   ・5 秒 or 10 秒固定 (TTS 尺 ×1.2 で bucket 選択)              │
│   ・出力: tmp/kling_<S>.mp4 + tmp/scene_<S>.trim.mp4             │
│                                                                  │
│ コスト: $0.42 (5s) or $0.84 (10s) / scene                       │
└─────────┬────────────────────────────────────────────────────────┘
          ▼
┌─ Stage 5 (音声合成 + リップシンク) ─────────────────────────────┐
│ scene_gen._scene_video_for_scene() + lipsync_client              │
│   1. ffmpeg で kling.mp4 + audio_<S>.m4a を mux                  │
│   2. Sync.so lipsync-2 で口の動きを TTS に同期                   │
│   3. 出力: tmp/scene_<S>.mp4 (= 完成 lipsync 済シーン)          │
│                                                                  │
│ コスト: ~$0.07 / scene (Sync.so credits)                        │
└─────────┬────────────────────────────────────────────────────────┘
          ▼
┌─ Stage 6 (字幕焼き込み = overlay) ──────────────────────────────┐
│ compositor.py (ffmpeg + libass)                                  │
│   ・全 scene を 1 mp4 に concat                                  │
│   ・lines[].text を字幕として焼き込み                            │
│     - timing: line.start/end ± silence-snap                      │
│     - subtitles[].text の手動チャンク制御も対応                  │
│   ・Claude Haiku で SNS caption を post_captions/<title>.md 生成 │
│   ・出力: output/reels_<TS>.mp4 + post_captions/                 │
│                                                                  │
│ コスト: Haiku ~$0.001 + ffmpeg (= ローカル無料)                 │
└─────────┬────────────────────────────────────────────────────────┘
          ▼
┌─ Stage 7 (final import = canonical 化) ─────────────────────────┐
│ scripts/auto_loop.py:_import_raw_as_final()                      │
│   ・output/reels_<TS>.mp4 を temp/<TS>/final/<HHMMSS>.mp4 に     │
│     コピー                                                       │
│   ・metadata.json.final_versions[] に追記                        │
│   ・最初の 1 本に is_canonical=true (= 以後の analytics / publish│
│     の正本になる)                                                │
│                                                                  │
│ 注: 本 phase は auto_loop からのみ呼ばれる (= manual main.py     │
│     からは到達しない)                                            │
└─────────┬────────────────────────────────────────────────────────┘
          ▼
┌─ Stage 8 (公開) ────────────────────────────────────────────────┐
│ platform_clients/ (YouTube / Instagram / TikTok)                 │
│   YouTube : Data API resumable upload で完全自動                 │
│              → analytics.posts に自動登録                        │
│   Instagram: caption をクリップボードへ + アプリ起動 (半自動)    │
│              → ユーザが register_post.py で URL 投入             │
│   TikTok  : 同上 + CSV 取込経路 (scripts/ingest_tiktok_csv.py)  │
│                                                                  │
│ 注: auto_loop はデフォルトで PRODUCTION_HUMAN_GATE_ENABLED=1     │
│     により Stage 8 の publish 直前で停止する                     │
└─────────┬────────────────────────────────────────────────────────┘
          ▼
┌─ Analytics (= 並走、cron) ──────────────────────────────────────┐
│ scripts/fetch_metrics.py で YouTube Data + Analytics API から     │
│   views / likes / completion_rate / 視聴時間 を取得             │
│   → data/analytics.db (SQLite) に時系列保存                     │
│ streamlit run scripts/dashboard.py で横断ビュー閲覧              │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. 実行モード (= 3 経路)

| モード         | 起動                                                       | スコープ                                                | 用途                  |
| -------------- | ---------------------------------------------------------- | ------------------------------------------------------- | --------------------- |
| **manual CLI** | `python3 main.py <name>` / `--resume <TS>`                 | 1 stage ずつ手動実行 (Stage 1-6)                        | デバッグ / 細かい制御 |
| **preview UI** | `python3 preview_server.py` + `cd frontend && npm run dev` | 各 stage 承認サイクル + 編集                            | 通常運用              |
| **フルオート** | `python3 scripts/auto_loop.py` (= cron)                    | URL 起点 Stage 0→7 まで完全自動 (Stage 8 は human gate) | 量産運用              |

---

## 5. AI / 外部 API モデル一覧

| Stage              | プロバイダ        | モデル                 | 用途                            | 単価                       |
| ------------------ | ----------------- | ---------------------- | ------------------------------- | -------------------------- |
| Stage 0 (analyze)  | Anthropic         | Claude Opus 4.7        | 映像 + 音声 → 抽象台本          | \$15/M in、\$75/M out      |
| Stage 0 (analyze)  | OpenAI or local   | Whisper                | word-level transcript           | \$0.006/min or 無料        |
| Stage 0 (rewrite)  | Google            | Gemini 2.5 Pro         | dialogue rewrite (= 翻案権配慮) | \$1.25/M in、\$5/M out     |
| Stage 0 (auto-tag) | Anthropic         | Claude Haiku           | 台本 auto-tag                   | \$0.25/M in                |
| Stage 2 (TTS)      | ElevenLabs        | eleven_v3              | TTS one-shot or per-character   | \$0.04 / 1K chars          |
| Stage 3 (BG)       | Google            | Gemini 3 Pro Image     | 背景 + キャラ合成               | \$0.04 / image             |
| Stage 4 (Kling)    | fal.ai            | kling-video/v3         | 静止画 → 動画                   | \$0.42 (5s) / \$0.84 (10s) |
| Stage 5 (lipsync)  | Sync.so           | lipsync-2              | 口の動き同期                    | \$0.07 / scene             |
| Stage 6 (caption)  | Anthropic         | Claude Haiku           | SNS caption 生成                | ~\$0.001 / video           |
| Stage 8 (publish)  | YouTube/IG/TikTok | Data / Graph / Display | 投稿自動化                      | 無料                       |

**1 動画あたり総コスト**: ~\$5-8 (= 30 秒 / 6 scene 想定、TTS + BG + Kling が支配的)

---

## 6. 段階的ゲート方式の不変条件

1. **各 stage の成果物は `temp/<TS>/tmp/` に保存**
2. **進捗は `tmp-progress.json`** (= stage 単位 status + approval flag)
3. **承認するまで次 stage は実行不可** (= preview UI で OK 押下が必須)
4. **上流変更で下流承認は自動 reset**:
   - 台本変更 (= breaking) → Stage 2-6 全 reset
   - subtitle_y のみ → Stage 6 のみ reset
   - speaker 変更 → Stage 2 reset (= 古い voice の動画が出る silent bug 解消、PR #209)
5. **個別 scene の再生成可能**: bg / kling / scene 単位で再実行ボタン (= 当該 stage 後続も連鎖 reset)

---

## 7. ステージ別の成果物まとめ

| Stage           | 主要アーティファクト                                                                                                      | 副産物                             |
| --------------- | ------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| 0. analyze      | `screenplays/auto_<sha>.json`                                                                                             | `analyze_jobs.error` / cost record |
| 1. script       | `temp/<TS>/screenplay.json` (snapshot) + metadata                                                                         | validation 結果                    |
| 2. tts          | `tts_full.mp3` + `tts_<S>_<L>.mp3` × N + `audio_<S>.m4a` + `tts_meta.json` + (multi-voice なら `tts_full.<base>.mp3` × N) | line.start/end 派生値              |
| 3. bg           | `tmp/bg_<S>.png`                                                                                                          | clip_library cache entry           |
| 4. kling        | `tmp/kling_<S>.mp4` + `tmp/scene_<S>.trim.mp4`                                                                            | clip_library cache entry           |
| 5. scene        | `tmp/scene_<S>.mp4` (lipsync 済)                                                                                          | (なし)                             |
| 6. overlay      | `output/reels_<TS>.mp4` + `post_captions/<title>.md`                                                                      | overlay metadata                   |
| 7. final_import | `temp/<TS>/final/<HHMMSS>.mp4`                                                                                            | `metadata.json.final_versions[]`   |
| 8. publish      | `metadata.json.published_posts[]` + `analytics.posts`                                                                     | 各 SNS の post URL                 |

---

## 8. キャラクター / Voice の対応

5 キャラ (= 各 5 wardrobe = 25 PNG) + 各 voice_id (PR #201):

| キャラ | 画像                               | voice_id               | gender / age         |
| ------ | ---------------------------------- | ---------------------- | -------------------- |
| f1     | base/suit/casual/loungewear/office | `0ptCJp0xgdabdcpVtCB5` | 女性 20 前半・活発   |
| f2     | 同上 (+ skirt 版 suit/casual)      | `gARvXPexe5VF3cKZBian` | 女性 20 後半・知的   |
| f3     | 同上 (+ mini skirt casual)         | `OSwaPSNdfituxkWcjlkR` | 女性 30 前半・優しい |
| m1     | 同上                               | `tpdfLrb2z3dwaZQdMBjP` | 男性 20 中盤・爽やか |
| m2     | 同上 (メガネ)                      | `vzIXwvf41vKosKu00hYj` | 男性 30 前半・知的   |

---

## 9. 主要不変条件 (= 守ること)

| 不変条件                                                                       | 場所                          |
| ------------------------------------------------------------------------------ | ----------------------------- |
| **台本は人間が作成** (= analyze 経由のみ)                                      | CLAUDE.md                     |
| **AI 課金が増える方向の変更は禁止**                                            | CLAUDE.md                     |
| **すべての実装は今後の台本全部に汎用対応** (= ハードコード禁止)                | CLAUDE.md                     |
| **指示の範囲を超えない** (= 字幕修正で動画再生成しない等)                      | CLAUDE.md                     |
| **段階的ゲート方式は破らない**                                                 | CLAUDE.md                     |
| **Clip Library cache 識別性** (= identity 4 軸一致 → 必ず同 pool hit)          | overview.md                   |
| **timing 計算は Python SSOT** (= compositor で一括解決)                        | overview.md                   |
| **snapshot は abstract で保存** (= 派生フィールドは compose で都度生成)        | abstract-screenplay-design.md |
| **screenplay 編集は project snapshot のみ** (= template は project 作成後不変) | overview.md                   |

---

## 10. 2026-05-17 (= 構造変化集中日) の PR 一覧

| PR   | 変更                                                                                                                                                                                      |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #199 | Remotion backend + 演出パーツ (scene_parts/global_parts) 全廃 → Stage 6 は compositor.py (ffmpeg) 単線                                                                                    |
| #200 | analyze の casting auto-fill + Pixar 3D 風キャラ画像再生成                                                                                                                                |
| #201 | 5 キャラに ElevenLabs voice_id 割当                                                                                                                                                       |
| #202 | per-character TTS (= N 並列フル生成 → 切出 → マージ)                                                                                                                                      |
| #203 | casting を参考動画から decouple (= alphabetical 順割当に簡素化)                                                                                                                           |
| #204 | Gemini 2.5 Pro による dialogue rewrite phase (= 翻案権配慮)                                                                                                                               |
| #205 | Stage 1 UI で SpeakerMappingSection が render されない bug 修正                                                                                                                           |
| #206 | analyze の speaker_profiles ↔ line.speaker 整合性 backfill                                                                                                                                |
| #207 | per-line SpeakerPicker の implicit active fallback                                                                                                                                        |
| #208 | ruff F401 unused imports 修正 (= CI lint 復旧)                                                                                                                                            |
| #209 | **speaker_to_ref / speaker_profiles schema 全廃** (= dead 抽象化撤廃、line.speaker は resolved id 直書き、SpeakerMappingSection 撤去 → per-line bulk-apply 統合、TTS 承認自動 reset 統合) |

---

## 11. 関連 docs

| 用途                       | パス                                                                          |
| -------------------------- | ----------------------------------------------------------------------------- |
| **プロジェクト全体ルール** | `CLAUDE.md`                                                                   |
| 戦略                       | `docs/content-strategy.md`                                                    |
| アーキテクチャ             | `docs/developments/overview.md` (= レイヤ + 依存方向 + データフロー)          |
| データ設計                 | `docs/abstract-screenplay-design.md`                                          |
| 設定根拠                   | `docs/architecture-decisions.md` (= モデル選定・コスト・プロンプト)           |
| 規約                       | `docs/developments/coding-rules.md` / `testing.md` / `ubiquitous-language.md` |
| 各機能の planning          | `docs/plannings/YYYY-MM-DD_*.md`                                              |

---

最終更新: 2026-05-17
