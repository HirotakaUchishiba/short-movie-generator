# BGM オーバーレイ Stage 設計書

## 1. 背景と目的

### 現状の課題

- 最終動画 (`output/reels_<TS>.mp4`) の音声は **TTS + リップシンク音声のみ** (`compositor._merge_scenes` の concat=a=1)。BGM が無い。
- 発話の間 (無音区間) が目立ち、ショート動画として単調・間が持たない。
- BGM を足す導線・フェーズが存在しない。

### 解決策

- 字幕オーバーレイ (Stage 6 = overlay) と取込 (Stage 7 = final_import) の間に、新 Stage「**bgm**」を追加する。
- overlaid 動画 (TTS + 字幕) に BGM を ffmpeg でミックスし、発話中は BGM を自動的に下げる (ダッキング)。
- BGM 取得源は MVP ではローカルライブラリ (商用利用可のフリー音源を `assets/bgm/` に配置)。生成 AI は Phase 2。

### 今回のスコープ (Phase 1)

やること:

- 新 Stage「bgm」を `STAGES` の overlay と final_import の間に追加。
- ffmpeg で BGM ミックス (amix + ダッキング sidechaincompress + ループ + フェード)。
- BGM ライブラリ (ローカル `assets/bgm/` + catalog) からの選択。
- 音声フローの変更 (overlay は `overlaid.mp4` 止まり、bgm が `reels_<TS>.mp4` を書く)。
- UI (StageBGM): BGM 選択・音量・ダッキング ON/OFF・試聴・「BGM なし」。
- 既存 project (BGM stage 追加前) の後方互換。

やらないこと (Phase 2 以降):

- 生成 AI BGM (fal.ai ElevenLabs Music / MiniMax 等)。
- シーン別 BGM 切替 (Phase 1 は動画全体で 1 曲)。
- 効果音 (SE) / イントロ・アウトロ。
- caption/emotion からの BGM 自動選曲。

## 2. アーキテクチャ設計

### 音声フローの変更 (最重要)

現状:

```
Stage 6 overlay : scene_*.mp4 → merged.mp4 → overlaid.mp4 → output/reels_<TS>.mp4 にコピー
Stage 7 import  : output/reels_<TS>.mp4 → temp/<TS>/final/<HHMMSS>.mp4
```

変更後:

```
Stage 6 overlay : scene_*.mp4 → merged.mp4 → temp/<TS>/overlaid.mp4 (reels には書かない)
Stage 6.5 bgm   : temp/<TS>/overlaid.mp4 + BGM → output/reels_<TS>.mp4 (amix + ダッキング)
Stage 7 import  : output/reels_<TS>.mp4 → temp/<TS>/final/<HHMMSS>.mp4 (変更なし)
```

ポイント: **`output/reels_<TS>.mp4` を書く責務を overlay から bgm へ移す**。これで final_import / auto_loop / ingest_video は「reels = 最終動画」という前提を変えずに済む。**BGM なし選択時は bgm stage が overlaid.mp4 をそのまま reels にコピー** (pass-through) するので、reels は常に bgm stage の出力になる。

### パッケージ構成

```
stages/bgm.py            # run_bgm: overlaid.mp4 + BGM → reels (新規)
bgm_library.py           # BGM catalog の load / 一覧 / パス解決 / license (新規)
assets/bgm/<file>        # ローカル BGM 音源 (商用利用可のフリー音源)
data/bgm_catalog.json    # BGM メタ [{id,title,file,mood,duration_sec,license,source}] (新規)
```

### 依存関係

- ffmpeg のみ: `amix` (TTS+BGM) / `sidechaincompress` (ダッキング) / `aloop` (BGM が動画より短い時のループ) / `afade` (頭尾フェード)。
- 新規外部 API は無し (Phase 1)。

### BGM 取得源の比較 (ユーザー要望の検討結果)

| 取得源                                                                                     | 商用ライセンス                | コスト               | 既存統合                   | 採用              |
| ------------------------------------------------------------------------------------------ | ----------------------------- | -------------------- | -------------------------- | ----------------- |
| **ローカルライブラリ** (Pixabay / Uppbeat / YouTube Audio Library から DL → `assets/bgm/`) | ✅ DL 時点で確定              | 無料                 | ◎ ファイル選択のみ         | **Phase 1 (MVP)** |
| ElevenLabs Music (fal.ai 経由)                                                             | ✅ clear (ライセンス済み学習) | $0.80/min            | ◎ 既存 ElevenLabs + fal.ai | Phase 2 本命      |
| MiniMax Music (fal.ai 経由)                                                                | ✅                            | $0.035/曲            | ◎ 既存 fal.ai              | Phase 2 (安価)    |
| Stable Audio 3.0                                                                           | ✅ Community License          | 無料(ローカル) / API | ○                          | Phase 2 候補      |
| Pixabay Music API                                                                          | ✅                            | 無料                 | ○                          | Phase 2 候補      |
| Suno / Udio                                                                                | ⚠️ 訴訟中 (Sony 係争中)       | $10/月               | △                          | **不採用**        |

MVP をローカルライブラリにする理由: ① ライセンスが DL 時点で確定し最も安全 (SNS 公開 = 商用利用)、② API 課金ゼロ、③ 実装が ffmpeg だけで最小。生成 AI は「動画の雰囲気に合わせて作曲する」価値があるが、ライセンス確認・コスト・実装が重いので Phase 2 に分離する。Phase 2 で生成 AI を入れるなら、既に使っている **fal.ai 上の ElevenLabs Music / MiniMax** が最有力 (新規 SDK 不要・商用 clear)。

注意: 既存の `assets/bgm/Tiktokダウンロード動画_bgm.wav` は参考動画由来でライセンス不明なため **商用利用不可**。Phase 1 では使わず、ライセンスフリー音源を別途配置する。

## 3. 実装設計

### 3.1 Stage 定義 (progress_store)

- `STAGES` に `"bgm"` を `"overlay"` と `"final_import"` の間に挿入。`next_stage` / `cascade_reset_after` は STAGES 順に依存するので自動反映。
- 再生成で後続 (final_import / publish) の承認をリセットする対象に bgm を含める。

### 3.2 run_bgm (stages/bgm.py)

責務: `temp/<TS>/overlaid.mp4` を入力に、選択 BGM をミックスして `output/reels_<TS>.mp4` を書く。

- metadata から BGM 選択 (id / 音量 / ダッキング) を読む。
- `id == "none"` なら overlaid.mp4 を reels にコピー (pass-through、処理なし)。
- 選択ありなら ffmpeg で: BGM を動画長に合わせ (aloop or trim) + afade (頭1s/尾1.5s) → amix で TTS と合成 → ダッキング ON なら sidechaincompress で発話中 BGM を圧縮。
- 失敗時は `mark_stage_failed` (errors envelope)。

### 3.3 ffmpeg ミックス (パラメータは config 化)

- `BGM_VOLUME_RATIO` (既定 0.18 = TTS 比 18%)。
- ダッキング: `sidechaincompress` (threshold / ratio / attack / release)。TTS を sidechain に入れ、発話中 BGM を -10〜-15dB 下げる。
- ループ: 動画 (45-60s) > BGM 曲長 のとき `aloop`。
- フェード: `afade=in` (0-1s) / `afade=out` (末尾 1.5s)。

### 3.4 BGM ライブラリ (bgm_library.py + data/bgm_catalog.json)

- `bgm_catalog.json`: `[{id, title, file, mood, duration_sec, license, source}]`。
- `list_bgm()`: catalog を返す (UI 用)。`resolve_bgm_path(id)`: `assets/bgm/<file>` 絶対パス。
- `license` フィールドで商用可否を明示し UI に表示。

### 3.5 metadata スキーマ

BGM 選択は **project metadata** に持つ (screenplay は台本の SSOT、BGM は演出選択なので分離)。

```json
"bgm": { "id": "calm_lofi_01", "volume": 0.18, "ducking": true }
```

- `id: "none"` で BGM なし。字幕 (overlay) とは独立 (BGM 変更で overlay 再焼きは不要)。

### 3.6 UI (StageBGM)

- BGM 一覧 (catalog、mood / license 表示)、選択、試聴 (`<audio>`)。
- 音量スライダ / ダッキング ON/OFF / 「BGM なし」。
- 「reels を焼く」ボタン (run_bgm)、プレビュー。StageOverlay のパターン踏襲。

### 3.7 backend / frontend wiring

- `staged_pipeline.STAGE_RUNNERS` に `"bgm": run_bgm`。
- `routes/stages.py` の再生成可能 stage set に "bgm" 追加。
- 新 route: `GET /api/bgm` (catalog) / `PUT /api/projects/<ts>/bgm` (選択保存)。
- frontend: `types.ts` の StageName / `StageProgressBar` / `StageBGM.tsx`。
- `scripts/auto_loop.py` の `INTERNAL_STAGES` に "bgm" 追加 (overlay の後)。auto_loop は既定 BGM (固定 id or mood) で自動選択。

### 3.8 後方互換

- BGM stage 追加前の既存 project は `temp/<TS>/overlaid.mp4` が無く reels が overlay 出力。→ run_bgm は「overlaid.mp4 が無ければ既存 reels をそのまま入力にする」fallback。
- bgm は **optional gate**: 既存 project (bgm 未承認) でも final_import に進めるよう、final_import の前提は overlay 承認のままにする。

## 4. テスト方針

- run_bgm 単体: BGM あり (amix トラック / duration が動画一致)、BGM なし (pass-through で reels == overlaid)。
- ダッキング: sidechaincompress filter が組まれること (聴感は手動確認)。
- ループ: 動画 > BGM 曲長 で duration が動画に一致。
- bgm_library: catalog load / license / 不正 id の graceful。
- 後方互換: overlaid.mp4 なし時の fallback。

## 5. 実装タスク

### Phase 1: ローカル BGM + ミックス (今回)

- [ ] 1. `STAGES` に "bgm" 挿入 + 初期化確認
- [ ] 2. `bgm_catalog.json` + `bgm_library.py` (list / resolve / license) + ライセンスフリー音源を `assets/bgm/` に配置
- [ ] 3. `stages/bgm.py` run_bgm: ffmpeg amix + ダッキング + ループ + フェード + pass-through
- [ ] 4. config: `BGM_VOLUME_RATIO` / ダッキング閾値等
- [ ] 5. metadata `bgm` フィールド + 読み書き
- [ ] 6. backend: STAGE_RUNNERS / routes (catalog, bgm 選択) / regen set
- [ ] 7. frontend: types / StageProgressBar / StageBGM
- [ ] 8. auto_loop: INTERNAL_STAGES に "bgm" + 既定選択
- [ ] 9. 後方互換 fallback + テスト

### Phase 2: 生成 AI / シーン別 (将来)

- [ ] 生成 AI BGM (fal.ai ElevenLabs Music / MiniMax) — caption / mood から生成
- [ ] BGM 自動選曲 (emotion arc から mood 推薦)
- [ ] シーン別 BGM / 効果音 (SE) / イントロ・アウトロ

## 6. リスクと対策

- **既存 reels フロー変更の影響**: overlay が reels を書かなくなる → final_import / ingest_video / 既存 project が壊れないか。対策: 後方互換 fallback (3.8) + テスト。
- **ダッキング調整**: TTS が聞き取りにくくならないよう音量・ダッキングを config 化 + UI で調整可に。
- **BGM ライセンス**: 商用利用可の音源のみ。catalog の license で明示。参考動画由来 (Tiktok...wav) は使わない。
- **stage gate の整合**: bgm を optional gate にし、既存 project (bgm なし) が final_import に進めるようにする。

## 9. 参考資料

- ffmpeg `amix` / `sidechaincompress` (ダッキング) / `aloop` / `afade`
- BGM 取得源: Pixabay Music / Uppbeat / YouTube Audio Library (フリー); ElevenLabs Music / MiniMax via fal.ai (生成 AI、商用 clear)
- 関連: `docs/developments/architecture.md` (レイヤ・依存方向)、`docs/developments/workflow.md` (Stage 別成果物)
