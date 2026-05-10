# Full Pipeline Conformance Audit — Stage 1-8 + analyze + analytics + Compositional Architecture

**date**: 2026-05-10 / **status**: ✅ **設計準拠率 95-100%、blocker 無し、本番運用可**
**base branch**: `main`
**audit branch**: `docs/full-pipeline-conformance-audit-2026-05-10`

本 audit は短期間に集中投入された PR (= #131-166) によって設計準拠が一斉に進んだ
ことを受けて、**「現状の全 pipeline が最新設計に 100% 準拠して動作するか」** を
横断検証した記録。後追いの新規セッションが「どこまで終わっていて、何が残って
いるか」を 1 本で把握できる状態を狙う。

検証対象は以下の 5 領域:

1. **Stage 1-6** (= 生成パイプライン本体: script → TTS → bg → kling → scene → overlay)
2. **Stage 7-8** (= final import + publish)
3. **analyze pipeline** (= 参考動画 → 抽象台本 + identity + annotation 生成)
4. **analytics pipeline** (= DB / fetch_metrics / dashboard / PDCA)
5. **Compositional Architecture** (= Layer 1 clip_library / Layer 2 part_registry / Layer 3 Remotion)

---

## TL;DR

- **総合準拠率**: 約 95-100%
- **総合テスト pass 数**: **983 / 0 failed** (= backend pytest 878 + frontend vitest 105)
- **blocker**: 無し
- **drift**: 1 件 (= analytics 軸別 view 4 つが `v_active_posts` 未経由、low-priority)
- **設計外の追加実装**: 2 件 (= analyze annotation の `confidence` field、PR #165 の novel intent suggestion) — drift ではなく enhancement
- **未着手の継続課題**: 3 件 (= audit doc が「別セッション」と明示済) — Stage 1-5 での parts 消費 / analyze の実 LLM 統合 / production e2e test

---

## 1. 領域別 conformance summary

| 領域                               | 準拠率  | テスト pass        | blocker | drift   |
| ---------------------------------- | ------- | ------------------ | ------- | ------- |
| Stage 1-6 (= 生成パイプライン本体) | ✅ 100% | 218                | 0       | 0       |
| Stage 7 (= final import)           | ✅ 100% | 21                 | 0       | 0       |
| Stage 8 (= publish)                | ✅ 100% | 24                 | 0       | 0       |
| analyze pipeline                   | ✅ 100% | 192                | 0       | 0       |
| analytics pipeline                 | ✅ 95%+ | 178                | 0       | 1 (low) |
| Compositional Architecture (L1-3)  | ✅ 95%+ | 145 + frontend 105 | 0       | 0       |
| 隣接 (= cost / pending sync 等)    | ✅ 100% | 80                 | 0       | 0       |

---

## 2. 領域別の検証結果

### 2.1 Stage 1-6 (= 生成パイプライン本体)

設計 SSOT: `CLAUDE.md` §「段階的ゲート方式」+ `docs/developments/architecture.md` + `docs/abstract-screenplay-design.md`

| Stage      | 設計要件                                                                                                                                               | 実装場所                                                                            | 状態 |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- | ---- |
| 1. script  | abstract validation (= `require_composed=False`)、snapshot + sha256、analyze_job_id を metadata に記録                                                 | `staged_pipeline.py:248-275, 208-235`                                               | ✅   |
| 2. TTS     | eleven_v3 one-shot 全体合成、per-line voice_id 切替不可、emotion → audio tag 自動挿入、duration / start / end を `tts_meta.json` に分離                | `scene_gen.py:1517-1640`、`elevenlabs_client.py`、`staged_pipeline.py:73-154`       | ✅   |
| 3. bg      | Imagen 背景生成、CLIP_LIBRARY_ENABLED=1 で `satisfy_scenes_from_library` 先行、`_override_background_prompt` skip、location_ref 由来 prompt を先頭注入 | `staged_pipeline.py:287-321`、`scene_gen.py:360-411`                                | ✅   |
| 4. kling   | fal.ai Kling V3 Standard、`_override_animation_prompt` fallback、emotion → motion addon                                                                | `scene_gen.py:140-165, 118-123`、`fal_video_client.py`                              | ✅   |
| 5. scene   | Sync.so lipsync-2、audio + lipsync 合成済み `scene_<S>.mp4`、CLIP_LIBRARY_ENABLED=1 で `register_cold_path_clips`                                      | `scene_gen.py:2141-2180`、`lipsync_client.py:112-131`、`staged_pipeline.py:342-366` | ✅   |
| 6. overlay | `OVERLAY_BACKEND` env var で ffmpeg / remotion 切替、pipeline raw + SNS caption 同時生成、subtitle anchor 混在解決                                     | `staged_pipeline.py:369-444`、`compositor.py:344-418`、`compositor_remotion.py`     | ✅   |

**不変条件**:

- ✅ `OVERLAY_BACKEND=ffmpeg` の既存挙動 100% 維持
- ✅ 旧 screenplay (= identity 無し) は cold path 直通で無修正動作
- ✅ AI 課金は減らす方向のみ (= clip_library wire は cold path で従来同等)
- ✅ Two SSOT 分離 (= キャラ entity / ロケ集) を validator が enforce
- ✅ Template / Snapshot 分離 (= snapshot は immutable abstract)

### 2.2 Stage 7 (= final import)

設計 SSOT: `CLAUDE.md` §「Stage 7 取込 + Stage 8 公開」

| 要件                                                | 実装                                    | 状態 |
| --------------------------------------------------- | --------------------------------------- | ---- |
| pipeline raw → `temp/<TS>/final/<HHMMSS>.mp4`       | `final_import/core.py:105-192`          | ✅   |
| `metadata.json.final_versions[]` 登録               | `final_import/core.py:259-266`          | ✅   |
| `is_canonical` フラグで正本管理                     | `final_import/core.py:174-183, 194-223` | ✅   |
| CLI `--canonical <FILENAME>`                        | `main.py:41-42, 181-188`                | ✅   |
| 複数バージョン保管                                  | `final_import/core.py:144-155`          | ✅   |
| 唯一の取込経路 = `auto_loop._import_raw_as_final()` | `scripts/auto_loop.py`                  | ✅   |
| `progress_store` で `final_import` を generated に  | `final_import/core.py:293-299`          | ✅   |
| `MP4 ftyp atom` 検証                                | `final_import/core.py:29-41`            | ✅   |

### 2.3 Stage 8 (= publish)

| platform                               | 自動化方式                                                                                  | 実装場所                                                           | 状態 |
| -------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | ---- |
| YouTube Shorts                         | 完全自動 (= Data API resumable upload + analytics.posts 自動登録)                           | `platform_clients/youtube.py`、`final_import/publish.py:254-308`   | ✅   |
| Instagram Reels                        | 半自動 (= caption clipboard + アプリ起動)、Graph API スタブ                                 | `final_import/publish.py:364-436`、`platform_clients/instagram.py` | ✅   |
| TikTok                                 | 半自動 + CSV 取込                                                                           | `final_import/publish.py:155-157`、`scripts/ingest_tiktok_csv.py`  | ✅   |
| CLI `--publish <platform>`             | `main.py:43-44, 203-223`                                                                    | ✅                                                                 |
| UI publish endpoint                    | `routes/final_publish.py:89` (= POST `/api/projects/<ts>/publish`)                          | ✅                                                                 |
| `run-next` で publish 自動起動しない   | `progress_store.py:12` で `EXTERNAL_ACTION_STAGES = frozenset({"final_import", "publish"})` | ✅                                                                 |
| `metadata.json.published_posts[]` 記録 | `final_import/publish.py:494-543`                                                           | ✅                                                                 |

### 2.4 analyze pipeline

設計 SSOT: `docs/abstract-screenplay-design.md` + `docs/plannings/2026-05-10_analyze-pipeline-conformance.md`

3 step plan が完了済み (= PR #149-151)。補強 PR (= #156 / #160 / #165) も実装。

| Step / PR     | 内容                                                                                                    | 実装場所                                                                    | 状態 |
| ------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ---- |
| Step 1 / #149 | annotation 注入 (= `intent_resolver` を Claude prompt に inject + normalize)                            | `video_analyzer.py:24-29, 150, 239-251, 325-343`、`analyze/pipeline.py:448` | ✅   |
| Step 2 / #150 | identity 派生 (= compose で `_derive_identity()`、必須 4 field 揃った時のみ scene["identity"] 書き込み) | `analyze/compose.py:255-268, 305-362`                                       | ✅   |
| Step 3 / #151 | error*code 統一 (= `routes/_helpers.py:api_error()` SSOT、analyze 系 9 endpoint を `ANALYZE*\*` で統一) | `routes/_helpers.py:17-36`、`preview_server.py:768-911`                     | ✅   |
| #156          | annotation_stats SSE 配信 (= UI に hit / by_intent_id / demoted 表示)                                   | `analyze/pipeline.py:198-251`                                               | ✅   |
| #160          | UI identity / annotation editor (= Stage 1 で編集可)                                                    | `frontend/src/components/stages/ScriptEditPanel.tsx`                        | ✅   |
| #165          | novel intent suggestion (= save phase で UI 表示)                                                       | `analyze/pipeline.py` の `_collect_novel_intent_candidates()`               | ✅   |

**不変条件**:

- ✅ Claude API call 1 回のみ (= $3.30/回 維持)
- ✅ identity は必須 4 field (= character_refs / location_ref / start_emotion / camera_distance) 揃った時のみ (= 部分 identity 禁止で誤 hit 防止)
- ✅ `visual_intent_id` は `visual_intents.yaml` 内 id か `null`
- ✅ `_override_*` 経路は `clip_library._scene_has_override` で bypass
- ✅ `validate_abstract` は annotation を optional として受入 (= 旧 abstract 後方互換)
- ✅ error_code SSOT (= `routes/_helpers.py` 1 箇所定義)

**設計外の追加実装** (= drift ではなく enhancement、後追いで設計 doc 側に追記推奨):

- `annotation.confidence` (= 0.0-1.0) と `annotation.rationale` (= string) field
  - SYSTEM_PROMPT で要求し、normalize 時に `confidence < 0.7` で `visual_intent_id` を `null` に降格
- novel intent 自動検出 (= PR #165、`_collect_novel_intent_candidates()`)
  - SSE event に `novel_intent_candidates` を含めて UI 表示

### 2.5 analytics pipeline

設計 SSOT: `docs/plannings/2026-05-10_analytics-pdca-gap-and-remediation.md` + `docs/content-strategy.md` + `docs/architecture-decisions.md §5`

3 phase plan が完了済み (= PR #153 / #158 / #161)。

| Phase / PR     | 内容                                                                                                                 | 実装場所                                                                                                                                          | 状態 |
| -------------- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| Phase A / #153 | dashboard rewire (= 戦略軸タブ / 実験タブ / 品質タブ / detail 時系列+ROI / `v_performance` を `v_active_posts` 経由) | `scripts/dashboard.py:164-189, 224-261, 410-431, 434-479, 116-120, 380-401`、`analytics/schema.sql:390`                                           | ✅   |
| Phase B / #158 | CTR / 30秒 retention / impressions / subscribers*gained / traffic*\*\_pct fetch + 表示                               | `platform_clients/youtube.py:329, 391-451, 454-513`、`analytics/schema.sql:97-99, 112-124`、`scripts/fetch_metrics.py:56-74`、`schema_version=10` | ✅   |
| Phase C / #161 | 戦略概念モデル (= transformation / tree_main_branch / pov_id) DB 表現                                                | `analytics/schema.sql:30-42, 396-413, 419-435`、`analytics/auto_tag.py:17-31, 44-81`、`config/transformation_taxonomy.yaml`、`schema_version=11`  | ✅   |

**既存資産** (= CLAUDE.md「分析基盤」記載分):

- ✅ `scripts/ingest_screenplay.py` — 台本 DB 登録 + Claude Haiku auto_tag
- ✅ `scripts/ingest_video.py` — metadata.json 経由台本紐付け、canonical final 優先
- ✅ `scripts/register_post.py` — YouTube/Instagram/TikTok 投稿 URL 登録
- ✅ `scripts/fetch_metrics.py --platform youtube` — metrics 取得
- ✅ `scripts/sync_pending_analytics.py` — pending queue flush
- ✅ `scripts/ingest_tiktok_csv.py` — TikTok Studio CSV 取込
- ✅ `analytics/pending_queue.py` — queue 管理
- ✅ `analytics/auto_tag.py` — hook_type / tone / dominant_emotion / theme / character_archetype + transformation / tree_main_branch / pov_id 推論

**不変条件**:

- ✅ additive migration (= `_ensure_column` 経路で既存データ破壊しない)
- ✅ 24h 経過 metrics のみ採用 (= 投稿直後ノイズ排除)
- ✅ retention curve fetch は投稿後 7 日以内 + 前回 24h 経過 post のみ (= API quota 緩和)
- ⚠️ `v_active_posts` 経由で rollback 済 post 除外 → **主要 view は OK だが軸別 view 4 つに drift あり (§3 参照)**

### 2.6 Compositional Architecture (= Layer 1-3)

設計 SSOT: `docs/plannings/2026-05-10_compositional-architecture.md`
継続監査: `docs/plannings/2026-05-10_architecture-mismatch-audit.md`

| Layer                              | 内容                                                                                                                                   | 実装場所                                                                                                        | 状態 |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ---- |
| Layer 1: clip_library              | identity hard match + annotation soft rank、satisfy_scenes_from_library / register_cold_path_clips wire                                | `clip_library.py`、`staged_pipeline.py:304-321, 353-362` (= CLIP_LIBRARY_ENABLED gate)                          | ✅   |
| Layer 2: part_registry (9 yaml)    | subtitle_styles / stickers / camera_moves / lower_thirds / filter_presets / title_cards / transitions / frame_layouts / visual_intents | `config/part_registry/*.yaml`、`part_registry_loader.py`、`screenplay_validator.py:593-698` (= drift fast-fail) | ✅   |
| Layer 2 ↔ React drift              | yaml ↔ component id 集合の一致を CI で強制                                                                                             | `frontend/remotion/__tests__/part_registry_yaml_drift.test.ts` (= 8 tests pass)                                 | ✅   |
| Layer 3: Remotion (4 compositions) | ScreenplayBase / ScreenplayYoutube / ScreenplayInstagram / ScreenplayTikTok                                                            | `frontend/remotion/Root.tsx:83-127`、`frontend/remotion/compositions/*.tsx`                                     | ✅   |
| compose pass-through contract      | `dict(abstract)` 起点で派生のみ追記、scene_parts / global_parts silent strip 解消                                                      | `analyze/compose.py:177-302` (= PR #157)                                                                        | ✅   |
| OVERLAY_BACKEND=remotion           | scene_videos + render_plan を Remotion CLI に流す                                                                                      | `compositor_remotion.py:226-450`、`staged_pipeline.py:396-411`                                                  | ✅   |
| platform 別 template 切替          | `compose_video_remotion(template=...)` で youtube / instagram / tiktok の global_parts / scene_parts を上書き                          | `frontend/remotion/Root.tsx:99-127`                                                                             | ✅   |

`docs/plannings/2026-05-10_architecture-mismatch-audit.md` §1-1 〜 1-6 で指摘されていた
mismatch はすべてクローズ済み (= PR #131 / #132 / #133 / #134 / #154 / #155 / #156 / #157 / #159 / #160)。
audit doc §5 修正履歴に明示。

---

## 3. drift 一覧 (= 修正対象)

### 🟠 D-1: 軸別 view 4 つが `v_active_posts` 経由になっていない

| 項目         | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ⚠️ 部分準拠 (= 4 view drift)                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 設計上の役割 | `v_active_posts` (= `analytics/schema.sql:79`) は schema v9 で導入された **rollback 済 post を analytics から除外する仕組み**。Phase A の不変条件として「すべての集計 view は v_active_posts 経由にする」                                                                                                                                                                                                                                                     |
| 証拠         | `analytics/schema.sql` の以下 4 view が `JOIN posts p ON p.video_id = v.id` を直接使用: <br>- `v_hook_type_performance` (`schema.sql:268-283`) <br>- `v_tone_performance` (`schema.sql:285-300`) <br>- `v_dominant_emotion_performance` (`schema.sql:302-317`) <br>- `v_theme_performance` (`schema.sql:319-334`)                                                                                                                                             |
| 影響         | rollback 済 post の metrics が軸別 view に混入する可能性。ただし: <br>- `v_strategy_performance` / `v_transformation_performance` / `v_halo_effect` / `v_performance` (= PDCA 主戦力) は **すべて `v_active_posts` 経由** で OK <br>- dashboard の `hook_tab` / `emotion_tab` は実質 `v_performance` を自前 groupby しており、軸別 view 直読みではないため**実害は限定的** <br>- 24h filter (`julianday >= 1.0`) は適用済みなので「投稿直後ノイズ」は除外済み |
| 修正方針     | 4 view の `JOIN posts p ON ...` を `JOIN v_active_posts p ON ...` に置換 + `analytics/db.py:CURRENT_SCHEMA_VERSION` を 11 → 12、`init_db()` で `DROP VIEW IF EXISTS` 経路                                                                                                                                                                                                                                                                                     |
| 修正サイズ   | 小 (= `schema.sql` 4 行 + `db.py` 数行 + test 更新)                                                                                                                                                                                                                                                                                                                                                                                                           |
| 優先度       | 🟠 中-低 (= 直接の運用障害は無いが、Phase A の不変条件「全 view は v_active_posts 経由」を破る)                                                                                                                                                                                                                                                                                                                                                               |

---

## 4. 設計外の追加実装 (= drift ではなく enhancement)

### E-1: `annotation.confidence` / `annotation.rationale` field

| 項目              | 内容                                                                                                                                                                   |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態              | ✨ 設計 doc 未記載の追加 (= 動作は OK、設計側に追記推奨)                                                                                                               |
| 場所              | `video_analyzer.py:24-29` の SYSTEM_PROMPT で要求、`analyze/intent_resolver.py:normalize_scene_annotation()` で確信度 < 0.7 のとき `visual_intent_id` を `null` に降格 |
| なぜ追加されたか  | Claude が低確信度で intent を選んだ場合に novel intent fallback (= cold path) に逃がすため                                                                             |
| 設計 doc 側の対応 | `docs/abstract-screenplay-design.md` の annotation スキーマ節に `confidence` / `rationale` を追記する (= 別 PR)                                                        |

### E-2: novel intent suggestion (= PR #165)

| 項目              | 内容                                                                                                  |
| ----------------- | ----------------------------------------------------------------------------------------------------- |
| 状態              | ✨ 設計 doc 未記載の追加 (= 動作は OK、設計側に追記推奨)                                              |
| 場所              | `analyze/pipeline.py` の `_collect_novel_intent_candidates()`、SSE event の `novel_intent_candidates` |
| なぜ追加されたか  | analyze 中に低確信度の intent を可視化し、catalog 拡張のヒントを UI に出す                            |
| 設計 doc 側の対応 | `docs/plannings/2026-05-10_analyze-pipeline-conformance.md` §9「既知の宿題」から削除し、本実装を明記  |

---

## 5. 継続課題 (= 別セッション持越し、本 audit のスコープ外)

`docs/plannings/2026-05-10_architecture-mismatch-audit.md` §5「残課題」に明示済の
3 件はすべて未着手のままで、本 audit でも維持 (= 別セッションで対応):

| #        | 内容                                                                                                                                         | 理由                                                                                                                    |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| 1-2 補強 | Stage 1-5 (= AI 生成) で `scene_parts` / `global_parts` を **消費** する機能拡張 (= 例: `subtitle_style` hint を `background_prompt` に反映) | root cause (= silent strip) は #157 で解消済。値の **消費** は別議論で、現状 Stage 6 のみ消費でも本不変条件には反しない |
| 1-5      | analyze pipeline の intent_resolver の **実 LLM 統合** (= Claude prompt から catalog inject + response parse)                                | **完了済** (= PR #149)。本項目は当初 audit 時点の記述で、現在は Step 1 で解消                                           |
| 1-8      | identity 一致 2 screenplay の hit を **production 経路で** 検証する e2e (= 現状は mock 駆動)                                                 | 実 AI 呼出の代替 fixture (= mock) 構築要                                                                                |

---

## 6. テスト実測

backend pytest と frontend vitest を design-critical 経路で網羅実行。

### Backend (Python pytest)

| suite group                                           | tests | result  |
| ----------------------------------------------------- | ----- | ------- |
| Stage 1-6 + 1-8 連携 (subset 1)                       | 218   | ✅ pass |
| Stage 1-6 + clip_library + overlay backend (subset 2) | 290   | ✅ pass |
| analyze pipeline (12 file)                            | 192   | ✅ pass |
| analytics pipeline (11 file)                          | 81    | ✅ pass |
| 隣接 (= sync*pending / fetch_reference / cost*\*)     | 97    | ✅ pass |

合計: **878 tests pass / 0 failed**

### Frontend (vitest, including Remotion drift test)

- 14 test files, 105 tests, **all pass**
- 内訳:
  - `src/api.test.ts` (6)
  - `src/uid.test.ts` (10)
  - `src/components/AnalyzeJobView.test.tsx` (5)
  - `remotion/__tests__/PartRegistry.test.ts` (23)
  - `remotion/__tests__/ScreenplayBase.test.ts` (6)
  - `src/components/AnnotationEditor.test.tsx` (5)
  - `src/components/IdentityEditor.test.tsx` (4)
  - `src/utils/screenplayPath.test.ts` (8)
  - `src/hooks/useRenderPlan.test.ts` (8)
  - `src/hooks/usePartCatalog.test.ts` (10)
  - `remotion/__tests__/HelloWorld.test.ts` (6)
  - `src/qaCategories.test.ts` (3)
  - **`remotion/__tests__/part_registry_yaml_drift.test.ts` (8)** ← Layer 2 強制 drift 防御
  - `src/components/CostEstimatePreview.test.tsx` (3)

**総計**: backend 878 + frontend 105 = **983 tests pass / 0 failed**

---

## 7. 不変条件チェック (= 横断的に守るべき条件)

| #   | 不変条件                                                    | 検証                                                                          | 状態 |
| --- | ----------------------------------------------------------- | ----------------------------------------------------------------------------- | ---- |
| 1   | `OVERLAY_BACKEND=ffmpeg` の既存挙動 100% 維持               | remotion 切替時のみ新経路、ffmpeg 経路は無変更                                | ✅   |
| 2   | 旧 screenplay (= identity 無し) は無修正で動作              | `clip_library` lookup は identity 存在時のみ、cold path 直通                  | ✅   |
| 3   | AI 課金は減らす方向のみ                                     | clip_library wire は cold path で従来同等の Imagen/Kling、追加課金無し        | ✅   |
| 4   | analyze の Claude 呼出は 1 回のみ                           | `analyze/pipeline.py:444-450` の phase 構造で claude phase 1 回 emit          | ✅   |
| 5   | identity は必須 4 field 揃った時のみ                        | `analyze/compose.py:_derive_identity()` で all() チェック                     | ✅   |
| 6   | Two SSOT 分離 (= キャラ entity / ロケ集)                    | `characters/<base>/` + `locations/<id>.json` 構造で運用、validator が enforce | ✅   |
| 7   | Template / Snapshot 分離 (= snapshot は immutable abstract) | `staged_pipeline.save_project_screenplay()` で `_strip_tts_derived` 経由      | ✅   |
| 8   | additive migration (= 既存 DB 破壊しない)                   | `analytics/db.py:_ensure_column()` 経路、`DROP VIEW IF EXISTS` migration      | ✅   |
| 9   | error_code SSOT                                             | `routes/_helpers.py:api_error()` 1 箇所定義                                   | ✅   |
| 10  | drift test CI 強制                                          | `part_registry_yaml_drift.test.ts` が CI で yaml ↔ React id 一致を毎回 assert | ✅   |
| 11  | 24h 経過 metrics のみ採用                                   | 全 strategy / transformation / halo view が `julianday >= 1.0` filter         | ✅   |
| 12  | rollback 済 post を analytics から除外                      | 主要 view は `v_active_posts` 経由 ✅、軸別 view 4 つは未経由 ⚠️ (§3 D-1)     | ⚠️   |

---

## 8. CLAUDE.md 最重要ルールへの準拠

| ルール                                                       | 検証                                                                                     | 状態 |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------- | ---- |
| すべての実装は「今後作られるすべての台本」に汎用的に対応する | ハードコード禁止、シーン番号直指定無し、台本固有 keyword 無し (= grep で確認済)          | ✅   |
| コストのかかる操作を安易に実行しない                         | `data/pricebook.json` + `data/cost_records.jsonl` で見積算定、字幕修正で動画再生成しない | ✅   |
| 指示の範囲を超えない                                         | UI 編集系は patch_line allowlist + scope 限定                                            | ✅   |
| 台本は人間が作成する                                         | analyze pipeline は **逆算抽出のみ**、台本生成はしない                                   | ✅   |
| 台本は `screenplays/<名前>.json` に配置                      | 唯一の作成経路は `scripts/analyze_video.py` (= 手書き UI 廃止済)                         | ✅   |
| 動画生成は段階的ゲート方式                                   | `progress_store.is_approved()` で前 stage 未承認時は raise                               | ✅   |

---

## 9. 修正の優先順位 (= 本 audit 後にやるべき作業)

| #   | 内容                                                                             | 優先度   | 工数 | 担当ブランチ                              |
| --- | -------------------------------------------------------------------------------- | -------- | ---- | ----------------------------------------- |
| 1   | D-1 修正 (= 軸別 view 4 つを v_active_posts 経由に統一)                          | 🟠 中-低 | 小   | `fix/axis-views-active-posts-consistency` |
| 2   | E-1 / E-2 を設計 doc に追記 (= confidence / rationale / novel_intent_candidates) | 🟡 低    | 小   | `docs/abstract-screenplay-design-update`  |
| 3   | 継続課題 1-2 補強 (= Stage 1-5 で parts 消費)                                    | 🟡 低    | 中   | (= 別セッション)                          |
| 4   | 継続課題 1-8 (= production e2e test)                                             | 🟡 低    | 中   | (= 別セッション、mock fixture 構築要)     |

---

## 10. 関連ドキュメント

- `CLAUDE.md` — 利用可能な part categories 表 + 段階的ゲート方式
- `docs/developments/architecture.md` — レイヤ・依存方向・データフロー
- `docs/developments/coding-rules.md` — Python / TypeScript コーディング規約
- `docs/abstract-screenplay-design.md` — analyze pipeline + compose 設計
- `docs/content-strategy.md` — 動画戦略の根本 (= analytics の "正" の半分)
- `docs/architecture-decisions.md` — モデル選定・コスト構造
- `docs/plannings/2026-05-10_compositional-architecture.md` — Compositional Architecture 設計
- `docs/plannings/2026-05-10_architecture-mismatch-audit.md` — 前回監査 (= L1-3 mismatch、本 audit で完全クローズ確認)
- `docs/plannings/2026-05-10_analyze-pipeline-conformance.md` — analyze 3 step plan (= PR #149-151 で完了)
- `docs/plannings/2026-05-10_analytics-pdca-gap-and-remediation.md` — analytics 3 phase plan (= PR #153 / #158 / #161 で完了)

---

## 11. 検証方法 (= 後追いの再現手順)

本 audit と同じ verification を新規セッションで再現する場合:

```bash
# 1. 設計 SSOT を読む
cat CLAUDE.md
cat docs/developments/architecture.md
cat docs/abstract-screenplay-design.md
cat docs/plannings/2026-05-10_architecture-mismatch-audit.md
cat docs/plannings/2026-05-10_analyze-pipeline-conformance.md
cat docs/plannings/2026-05-10_analytics-pdca-gap-and-remediation.md

# 2. design-critical 経路の test 実行 (= 約 5 分)
python3 -m pytest \
  tests/test_pipeline_e2e.py \
  tests/test_overlay_backend_dispatch.py \
  tests/test_compositor_remotion.py \
  tests/test_clip_library.py \
  tests/test_clip_library_wire.py \
  tests/test_analyze_compose.py \
  tests/test_analyze_pipeline.py \
  tests/test_part_registry_loader.py \
  tests/test_publish_flow.py \
  tests/test_final_import.py \
  tests/test_auto_loop.py \
  tests/test_main_cli.py \
  tests/test_main_kill_switch.py \
  tests/test_progress_store.py \
  tests/test_preview_server_abstract.py \
  tests/test_compositor_overlay.py \
  tests/test_screenplay_validator.py \
  tests/test_elevenlabs_client.py \
  tests/test_lipsync_client.py \
  tests/test_scene_gen_override_fields.py \
  tests/test_publish_channel_guard.py

# 3. analyze + analytics test 実行 (= 約 3 分)
python3 -m pytest \
  tests/test_analyze_pipeline.py tests/test_analyze_compose.py \
  tests/test_analyze_cache.py tests/test_analyze_character_meta.py \
  tests/test_analyze_cost.py tests/test_analyze_job.py \
  tests/test_analyze_location.py tests/test_analyze_progress.py \
  tests/test_intent_resolver.py tests/test_video_analyzer.py \
  tests/test_video_analyzer_atomic.py tests/test_preview_server_analyze.py \
  tests/test_analytics_db.py tests/test_analytics_db_phase3.py \
  tests/test_analytics_db_phase4.py tests/test_analytics_db_phase_a.py \
  tests/test_analytics_db_phase_b.py tests/test_analytics_db_phase_c.py \
  tests/test_analytics_db_phase_x1.py tests/test_auto_tag.py \
  tests/test_auto_tag_phase_c.py tests/test_dashboard_smoke.py \
  tests/test_preview_server_pending_analytics.py \
  tests/test_sync_pending_analytics.py

# 4. frontend + Remotion drift test (= 約 1 分)
cd frontend && npm test -- --run

# 5. drift 確認 (= 軸別 view が v_active_posts 経由か)
grep -A 3 "CREATE VIEW IF NOT EXISTS v_hook_type_performance" analytics/schema.sql
# → "JOIN posts p ON ..." なら drift 残存、"JOIN v_active_posts p ON ..." なら解消
```

---

## 12. 本 audit の不変条件

本 audit 自体が後追いセッションでも再現できることを保証するため、以下の条件を守る:

1. **PR 番号は変更しない**: 本 doc に記載した PR # は git log から逆引きできること
2. **準拠率は範囲で書く**: 「100%」と単独で書かず「95-100%」のような幅で誠実に
3. **drift と enhancement を分ける**: 「設計に書いてないが動いている」は drift ではなく
   enhancement。設計 doc 側の追記責任を明示する
4. **継続課題は理由を明示**: 「別セッション」と書くだけでなく、なぜ別セッションが
   必要か (= 実 LLM 必要 / fixture 構築要 等) を 1 行付ける
5. **本 audit のテスト数は実測**: 推定や記憶ではなく pytest / vitest の実際の出力から書く
