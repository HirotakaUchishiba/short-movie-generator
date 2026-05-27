# 効果音 (SE) オーバーレイ Stage 設計書

## 1. 背景と目的

### 現状の課題

- BGM stage (= 連続する背景音楽、PR #372) は追加したが、特定タイミングの効果音
  (SE = ポン / シャキーン / ヒュッ 等) が無い。
- SE は強調・リアクション・場面転換の演出を加えるが、**「動画のどのタイミングに、
  どの SE を載せるか」の配置判断**が必要で、全体に 1 曲を敷く BGM より複雑。

### 解決策

- BGM stage の後に SE stage「se」を追加 (overlay → bgm → **se** → final_import)。
- SE の配置 (いつ・どれ) を screenplay の **既存メタ (emotion / visual_intent /
  scene 境界 / line timing) から自動導出**し、UI で手動微調整する (= 全体最適)。
- SE ファイルはローカル (`assets/se/` + catalog)。生成 AI は Phase 2。

### 今回のスコープ (Phase 1)

やること:

- 新 stage「se」を bgm と final_import の間に追加。
- **reels を書く責務を bgm → se に移譲** (各 stage は中間ファイルを受け渡す)。
- SE ライブラリ (ローカル `assets/se/` + `data/se_catalog.json`)。
- **SE 自動配置 (se_planner)**: emotion → SE / visual_intent(reaction系) → SE /
  scene 境界 → トランジション SE。配置案を metadata.se に生成。
- 手動編集 (UI で SE 追加 / 削除 / 時刻 / 音量、自動案の取捨)。
- ミックス: bgm_mixed.mp4 + 各 SE (adelay で絶対時刻配置 + amix)。
- 後方互換 (se 未承認でも final_import に進める)。

やらないこと (Phase 2 以降):

- char_ts による強調語 SE (line 内の特定語のタイミングに SE)。
- 生成 AI SE (fal.ai 等)。
- BGM / TTS / SE の音量自動バランス最適化。
- ループ SE / 環境音 (連続音は BGM の領域)。

## 2. アーキテクチャ設計

### 音声フローの変更 (肝)

現状 (BGM stage まで):

```
overlay → temp/<TS>/overlaid.mp4
bgm     → output/reels_<TS>.mp4   (BGM ミックス or overlaid を pass-through)
final_import → reels
```

変更後 (SE stage 追加):

```
overlay → temp/<TS>/overlaid.mp4
bgm     → temp/<TS>/bgm_mixed.mp4 (BGM ミックス or overlaid を pass-through)  ← reels でなく中間へ
se      → output/reels_<TS>.mp4   (SE 重ね or bgm_mixed を pass-through)      ← reels を書く責務をここへ
final_import → reels (無変更)
```

ポイント: **reels を書く責務を「最後の音声 stage」= se に集約**する。各 stage は
中間ファイルを受け渡し、SE / BGM の有無に関わらず reels は常に se の出力になる。
BGM stage の出力を reels → `bgm_mixed.mp4` に変える (= PR #372 の小調整)。これで
final_import は無変更で「reels = 最終音声」を取り込める。

### パッケージ構成

```
se_planner.py        # 既存メタ → SE 配置案の自動導出 (= 全体最適の中核、新規)
stages/se_mix.py     # mix_se: bgm_mixed.mp4 + 複数 SE → reels (adelay+amix) (新規)
se_library.py        # SE catalog load / resolve / category (新規)
assets/se/<file>     # ローカル SE 音源 (商用利用可)
data/se_catalog.json # SE メタ [{id,title,file,category,license}] (新規)
```

### 依存関係

- ffmpeg: `adelay` (各 SE を絶対時刻に配置) + `amix` (bgm_mixed + 全 SE)。
- 既存メタ: `stages/emotion.dominant_emotion` / `visual_intents.yaml` /
  `compositor._scene_offsets_from_videos` (絶対秒) / char_ts (Phase 2)。

## 3. 実装設計

### 3.1 SE 配置の自動導出 (se_planner.py) ← 全体最適の中核

責務: screenplay (完成状態) から SE 配置案
`[{time, se_id, volume, source, reason}]` を導出する。「いつ・どれ」を既存メタから
決める。**特定台本へのハードコードはせず、config mapping + catalog category で汎用化**。

導出ルール (Phase 1):

| トリガ (既存メタ)                                                          | SE category      | 配置時刻                                        | 例                           |
| -------------------------------------------------------------------------- | ---------------- | ----------------------------------------------- | ---------------------------- |
| `line.emotion` ∈ EMOTION_SE_MAP                                            | reaction / sting | line の絶対開始秒 (= scene offset + line.start) | 驚き → 「シャキーン」        |
| `scene.annotation.visual_intent_id` ∈ {reaction_surprise, reaction_relief} | reaction         | 該当 scene の開始秒                             | reaction_surprise → 「ハッ」 |
| scene 境界 (i→i+1)                                                         | transition       | `scene_offsets[i+1]`                            | 「ヒュッ」                   |

- emotion → category は config `EMOTION_SE_MAP` (新設)。category 内の具体 se_id は
  catalog を category でフィルタして選ぶ。
- 絶対時刻は `compositor._scene_offsets_from_videos` (実尺累積、字幕と同じ基準) +
  `line.start`。字幕・発話と同じ timeline に載るので SE がズレない。
- `source="auto"` / `reason` (どのルールで置いたか、UI 表示用)。
- 鳴りすぎ防止に `SE_MAX_PER_SCENE` (config) で 1 scene あたり上限。

### 3.2 SE ミックス (stages/se_mix.py)

責務: bgm_mixed.mp4 に複数 SE を絶対時刻で重ねて reels を書く。

- 各 SE 入力を `adelay=<time_ms>` で絶対時刻に配置 + `volume`。
- bgm_mixed の音声 + 全 SE を `amix` (inputs = 1 + N、normalize=0)。
- SE が空なら bgm_mixed を reels に pass-through (copy)。映像は `-c:v copy`。

### 3.3 SE ライブラリ (se_library.py + se_catalog.json)

- `se_catalog.json`: `[{id, title, file, category, license, source}]`。
- category: `sting` / `transition` / `reaction` / `emphasis`。
- `list_se()` / `resolve_se_path(id)` / `se_by_category(cat)`。bgm_library と同型。

### 3.4 metadata スキーマ

```json
"se": {
  "items": [
    {"time": 12.34, "se_id": "surprise_01", "volume": 0.6, "source": "auto", "reason": "emotion:驚き"}
  ],
  "auto_generated_at": "..."
}
```

- `run_se` は `metadata.se.items` を読んでミックス。BGM (`metadata.bgm`) と独立。
- 自動導出は明示操作 (UI / API) で 1 回実行して items を保存 → 以後 UI で編集。

### 3.5 UI (StageSE)

- 「自動配置を生成」ボタン (se_planner 実行 → items 一覧)。
- 各 SE 行: 時刻 (動画プレイヤーからスナップ) / se_id 選択 (category 別) / 音量 /
  削除。手動追加。試聴 (`/asset/se/<file>`)。
- 「reels を焼く」(run_se) + プレビュー。StageBGM / StageOverlay のパターン踏襲。

### 3.6 backend / frontend wiring

- `STAGES` に "se" を bgm と final_import の間 (+ `_CASCADE_STAGES`)。
- `staged_pipeline`: `run_bgm` の出力を `bgm_mixed.mp4` に変更 + `run_se` 追加 +
  `STAGE_RUNNERS` / dispatch / per-stage regen。
- `routes/se.py`: `GET /api/se` (catalog) / `PUT /api/projects/<ts>/se` (items 保存) /
  `POST /api/projects/<ts>/se/auto` (自動導出) / `/asset/se/<file>` (試聴)。
- `auto_loop` `INTERNAL_STAGES` に "se" (既定 = 自動導出 or 空でも可)。
- frontend: types (StageName se + SeItem) / StageProgressBar / StageSE.tsx /
  api / ProjectList。

### 3.7 後方互換

- bgm が reels → bgm_mixed.mp4 に変わるので、既存 project (reels が bgm 出力) は
  se が「bgm_mixed.mp4 が無ければ既存 reels を入力にする」fallback。
- se は optional gate (= 既存 project が final_import に進める)。

## 4. テスト方針

- se_planner: emotion / visual_intent / scene 境界 → 配置案 (時刻・category)。
  汎用性 (特定台本でなく mapping ベース)、SE_MAX_PER_SCENE 上限。
- se_mix: 複数 SE の adelay+amix (時刻・duration)、SE 空 pass-through。
- se_library: catalog / resolve / category / 不正 id。
- run_se: 自動導出 + ミックス + pass-through + 後方互換 fallback。
- bgm 出力変更 (bgm_mixed.mp4) の回帰 + STAGES/e2e 更新 (bgm と同様)。

## 5. 実装タスク

### Phase 1

- [ ] STAGES に se 挿入 (+ \_CASCADE_STAGES) + bgm 出力を bgm_mixed.mp4 に変更
- [ ] se_catalog.json + se_library.py + テスト用 SE 音源 (ffmpeg 自作)
- [ ] se_planner.py (emotion / visual_intent / scene 境界 → 配置案) + config
      EMOTION_SE_MAP / SE_MAX_PER_SCENE
- [ ] stages/se_mix.py (adelay + amix + pass-through)
- [ ] staged_pipeline.run_se + run_bgm 出力変更 + STAGE_RUNNERS / dispatch / regen
- [ ] metadata.se + routes/se.py (catalog / items / auto / asset)
- [ ] auto_loop INTERNAL_STAGES
- [ ] frontend (types / StageProgressBar / StageSE / api / ProjectList)
- [ ] テスト + pytest / tsc

### Phase 2

- [ ] char_ts 強調語 SE (line 内の特定語タイミング、text_mapping.find_line_time_range)
- [ ] 生成 AI SE (fal.ai)
- [ ] BGM / TTS / SE の音量自動バランス

## 6. リスクと対策

- **bgm 出力変更の影響**: bgm が reels → bgm_mixed.mp4。final_import / 既存 project
  が壊れないか → se が reels を書く + 後方互換 fallback + テスト。
- **SE 自動配置の過剰**: emotion が多いと SE が鳴りすぎ → 自動案は「候補」で UI 取捨 +
  `SE_MAX_PER_SCENE` 上限。
- **SE 音量バランス**: SE が TTS / BGM を邪魔しない既定音量 (config) + UI 調整。
- **ライセンス**: 商用可の SE のみ。catalog の license で明示。

## 9. 参考資料

- ffmpeg `adelay` / `amix`
- 既存メタ: `stages/emotion.py` / `config/part_registry/visual_intents.yaml` /
  `compositor._scene_offsets_from_videos` / `stages/text_mapping.py` (char_ts)
- BGM stage 雛形: `docs/plannings/2026-05-27_bgm-overlay-stage.md`
