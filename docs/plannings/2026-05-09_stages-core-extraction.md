# scene_gen.py 完全 stages 分割 — 残作業ロードマップ

**date**: 2026-05-09 / **base branch**: `feat/stages-core-extraction-roadmap`

`scene_gen.py` (= 約 2300 LOC) を `stages/<name>.py` に per-stage 分割する
作業のうち、**helper 系 (text_utils / emotion) は完了** (PR #86 / #88)。
残るのは **core 関数群** で、それぞれが大きく依存関係が複雑なため
独立 PR で慎重に進める必要がある。

## 残タスク (= 4 PR 想定)

各 PR は **1 stage = 1 PR** で進め、実装中は scene*gen の公開 API
(= staged_pipeline / preview_server / cron が import している) を一切
変えない。internal な `*` プレフィックス helper のみを移動する。

### PR-A: stages/tts.py (= 最大の塊、~600 LOC)

対象関数:

- `_resolve_inline_tag`
- `_build_screenplay_text`
- `_build_position_to_time_map`
- `_pcm_silence_mask`
- `_select_silence_cuts`
- `_apply_silence_trims`
- `_compose_screenplay_one_shot`
- `generate_screenplay_tts_one_shot`
- `generate_tts_for_screenplay`
- `regen_tts_line` / `regen_tts_full`

依存:

- elevenlabs_client
- audio_dynamics
- furigana_store
- staged_pipeline (= save_tts_meta)

## PR-B: stages/bg.py (= ~500 LOC)

対象関数:

- `_resolve_character_refs`
- `_build_background_prompt`
- `_detect_storyboard_image`
- `_generate_background_with_retry`
- `_generate_single_background`
- `_scene_bg_inputs`
- `_build_bg_cache_meta`
- `bg_scan_cache` / `bg_commit_cache` / `bg_generate_fresh`
- `generate_backgrounds`
- `_clear_bg_downstream`

依存:

- imagen_client / bg_cache / atomic_assets / artifact_integrity

## PR-C: stages/kling.py (= ~600 LOC)

対象関数:

- `_get_animation_prompt`
- `_augment_animation_prompt`
- `_generate_kling`
- `_kling_for_scene`
- `_trim_and_finalize_kling`
- `generate_kling_for_screenplay`
- `regen_kling_scene`
- kling cache 関連 (`_kling_cache_meta` 等)

依存:

- fal_video_client / kling_cache / artifact_integrity

## PR-D: stages/scene_compose.py + cleanup

対象関数:

- `_get_duration` / `_trim_video` / `_extend_video_to_duration`
- `_replace_audio` / `_prepare_background`
- `_build_scene_audio` / `_apply_volume`
- `_trim_internal_pauses`
- `_scene_video_for_scene`
- `assemble_scene_videos`
- `build_merged_tts_preview`

cleanup 工程:

- scene_gen.py を re-export shim に削減 (= 既存 import 互換維持)
- 全 stage helper を stages/ 配下に集約

## 移行原則

1. **scene_gen.py の公開 API シグネチャは一切変えない**。
2. 各 PR で `stages/<name>.py` を新規追加し、`scene_gen.py` 内の定義を
   `from stages.<name> import ...` に置換する shim 化。
3. shim 後の `scene_gen.py` の関数本体は 1 行 (= delegate のみ) になる。
4. 各 PR で 1233+ 件の pytest を全件 PASS で維持する。
5. PR 説明に「移行した関数一覧」「scene_gen.py の残 LOC」「依存テスト件数」
   を明記。

## 過去の参考 PR

- PR #86: `routes/_helpers.py` + `stages/text_utils.py` 抽出 (= 第 1 step)
- PR #88: `stages/emotion.py` 抽出 (= 第 2 step)
- PR #92: `job_runner.py` 抽出 (= preview_server 側の前段作業の参考)

これらの PR と同じパターン (= shim 残し + 段階移行) で進める。
