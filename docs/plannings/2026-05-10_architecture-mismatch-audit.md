# Compositional Architecture: 設計と実装の乖離 audit

**date**: 2026-05-10 / **status**: 🔴 **重要 — 実装は設計に部分準拠**

`2026-05-10_compositional-architecture.md` (= 設計案) と
`2026-05-10_parts-and-composition-overview.md` (= 図解) は **設計どおり完成している
前提** で書かれているが、実装には **意図的に skeleton で止めた箇所** と
**実装の wire 漏れ** が複数残っている。

本 doc はそのギャップを **正直に列挙** することが目的。後任が「設計 doc 通りに
動いている」と誤解しないようにする。

直近の修正は本 audit doc を main 入れた直後から並列で進める (= mismatch を 1 件ずつ
別 PR で潰す方針)。

---

## TL;DR

- **準拠度**: 約 40-50%。**Layer 3 (Remotion 描画) は完全準拠**、**Layer 2 (8 part
  categories) も完全準拠**だが、**Layer 1 (clip library) は skeleton のままで
  production code から呼ばれていない**
- 矛盾の本質: 「**上流 (= screenplay 受入) と下流 (= Remotion 描画) は新設計、
  中流 (= AI 生成 + cache) は旧設計のまま**」
- 結果: 設計が掲げた最大の利点 = **「同じ identity の scene なら 2 回目以降 AI 課金 0」が
  発動していない**

---

## 1. 観点別 mismatch 一覧

### 🔴 1-1: clip_library が production 経路から完全に dead

| 項目         | 内容                                                                                                                                               |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ❌ 未準拠                                                                                                                                          |
| 証拠         | `grep -rln "clip_library" --include="*.py" \| grep -v tests` の結果は `screenplay_validator.py` の **コメント参照のみ** (= import 0 件)            |
| 影響         | `lookup_clip_pool` / `select_variant` / `register_clip_entry` が production から呼ばれない。 同じ identity の scene でも毎回 Imagen + Kling が走る |
| 設計上の役割 | Layer 1 cache。**設計の中核機能**で、cost 削減と variant 多様性の根拠                                                                              |
| 修正先       | `scene_gen.py` の bg / kling 生成ステージで `clip_library.lookup_clip_pool()` を呼ぶ経路を追加                                                     |

### 🔴 1-2: Stage 1-5 が新フィールド `scene_parts` / `global_parts` を無視

| 項目   | 内容                                                                                                                                                                                 |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 状態   | ⚠️ 部分準拠 (= validator が受入れるが consumer は Stage 6 のみ)                                                                                                                      |
| 証拠   | grep 結果: `scene_parts` / `global_parts` を読むのは `compositor_remotion.py` (= Stage 6) と `screenplay_validator.py` (= スキーマ定義) だけ                                         |
| 影響   | screenplay JSON に `scene_parts.subtitle_style.id = "karaoke_bold"` を書いても、Stage 1-5 (= AI 生成) は旧 background_prompt / animation_prompt を見るだけ。Stage 6 でだけ反映される |
| 修正先 | (Phase 1 cold path 接続後の課題) 各 Stage で新フィールドを正しく forward する経路を整備                                                                                              |

### 🔴 1-3: `_override_background_prompt` / `_override_animation_prompt` 未配線

| 項目   | 内容                                                                                                                         |
| ------ | ---------------------------------------------------------------------------------------------------------------------------- |
| 状態   | ❌ 未準拠                                                                                                                    |
| 証拠   | validator は `screenplay_validator.py:262` で受け入れているが、`scene_gen.py` / `bg_cache.py` / `kling_cache.py` で参照無し  |
| 影響   | 「novel intent 用の escape hatch」として設計された fallback が動かない                                                       |
| 修正先 | `scene_gen.py` の `_build_background_prompt` / `_augment_animation_prompt` で `scene._override_*` があれば override 採用する |

### 🟠 1-4: validator に part_registry 整合性チェック未実装

| 項目   | 内容                                                                                                                         |
| ------ | ---------------------------------------------------------------------------------------------------------------------------- |
| 状態   | ❌ 未準拠                                                                                                                    |
| 証拠   | `screenplay_validator.py:78, 259` に「Phase 4 で part_registry の整合性チェックを足す」コメントが 2 箇所残るが実装無し       |
| 影響   | 存在しない `subtitle_style.id: "ghost_style"` を validator が pass。render 時に `PartRenderer` が throw する遅い fail になる |
| 修正先 | `screenplay_validator.py` に `_check_part_registry()` を追加。`config/part_registry/*.yaml` を load して id 一致を verify    |

### 🟠 1-5: Phase 6 intent_resolver が LLM 統合されていない

| 項目   | 内容                                                                                                                                                                       |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態   | ⚠️ 部分準拠 (= helper module は完成、integration は skeleton)                                                                                                              |
| 証拠   | `analyze/intent_resolver.py` は実装 + 14 unit tests pass だが、`scripts/analyze_video.py` / `analyze/pipeline.py` から import されない                                     |
| 影響   | analyze pipeline は引き続き visual_intent_id を出力しない。screenplay の identity / annotation は手書きのみ                                                                |
| 修正先 | `analyze/pipeline.py` の Claude prompt に `format_catalog_for_prompt()` を inject、response を `parse_intent_assignment()` でパース。実 LLM 検証込みなので別セッション推奨 |

### 🟡 1-6: StageScript UI で新フィールド編集不可

| 項目   | 内容                                                                                                                                                 |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態   | ❌ 未準拠                                                                                                                                            |
| 証拠   | `frontend/src/components/stages/ScriptEditPanel.tsx` で編集できるのは `location_ref` / `camera_distance` / `animation_style` 等の旧フィールドのみ    |
| 影響   | ユーザーが新パーツ (= karaoke_bold subtitle / sticker / lower_third 等) を使うには **screenplay JSON を手書き** する必要がある                       |
| 修正先 | `ScriptEditPanel.tsx` に "パーツ編集" セクションを追加。`config/part_registry/*.yaml` を `/api/parts/catalog` 経由で fetch して enum selector を生成 |

### 🟡 1-7: README.md の Phase 完了テーブルが楽観的

| 項目   | 内容                                                                                                                                                    |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態   | ⚠️ 部分準拠                                                                                                                                             |
| 証拠   | `frontend/remotion/README.md:131-149` の Phase テーブルで Phase 1 / 6 が ✅ になっているが、いずれも **production wire 無しの skeleton** で「動かない」 |
| 影響   | 後任が「Phase 1 完了 = clip_library が動いている」と誤解する                                                                                            |
| 修正先 | テーブルを ⚠️ "skeleton" に修正、本 audit doc へのリンクを README に追加                                                                                |

### 🟡 1-8: テストカバレッジに e2e 不在

| 項目   | 内容                                                                                                                                   |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| 状態   | ⚠️ 部分準拠 (= unit test は厚いが e2e なし)                                                                                            |
| 証拠   | `tests/test_clip_library.py` (28) / `tests/test_intent_resolver.py` (14) / `tests/test_compositor_remotion.py` (34) はすべて mock 駆動 |
| 影響   | 「2 つの screenplay で identity が一致したら同じ clip が hit する」を **production 経路で** 検証する e2e がない                        |
| 修正先 | `tests/test_pipeline_e2e_compositional.py` を新設、Phase 1 wire 完了後に追加                                                           |

### ✅ 1-9: 準拠している部分 (= 設計どおり動く)

参考までに、設計どおり完成している領域も明記する:

| 領域                                     | 状態 | 検証                                                                                 |
| ---------------------------------------- | ---- | ------------------------------------------------------------------------------------ |
| **Layer 2: 8 part categories**           | ✅   | yaml SSOT + React + drift test (`part_registry_yaml_drift.test.ts`) で id 一致を強制 |
| **Layer 3: 4 compositions**              | ✅   | `npx remotion compositions` で 5 entries 表示、実 render 検証済み                    |
| **OVERLAY_BACKEND dispatch (Stage 6)**   | ✅   | `staged_pipeline.run_overlay` で env var により ffmpeg / remotion が切替             |
| **compositor_remotion 視覚一致**         | ✅   | TS 20260425_190242 で字幕位置 / wrap が ffmpeg backend と視覚的に揃う (= 修正済)     |
| **part registry yaml ↔ component drift** | ✅   | drift test が 8 categories を自動 iterate                                            |

---

## 2. 修正の優先順位

| #   | 修正                                         | 影響                               | 工数 | 担当ブランチ                             |
| --- | -------------------------------------------- | ---------------------------------- | ---- | ---------------------------------------- |
| 1   | 本 audit doc (= mismatch 明文化)             | 後任の誤解防止                     | 小   | `docs/architecture-mismatch-audit`       |
| 2   | README/CLAUDE.md の Phase status 訂正        | 同上 (= 即時)                      | 小   | `docs/honest-phase-status`               |
| 3   | validator: part_registry 整合性              | render 前の早期 fail で UX 改善    | 小   | `feat/validator-part-registry-integrity` |
| 4   | scene*gen: `\_override*\*` 配線              | novel intent escape hatch          | 小   | `feat/override-fields-bg-kling`          |
| 5   | scene_gen: clip_library wire                 | **AI 課金大幅削減** (= 設計の中核) | 中   | `feat/wire-clip-library-to-scene-gen`    |
| 6   | StageScript UI の新フィールド編集            | UI からパーツ使用可能化            | 大   | (= 別セッション、別 PR)                  |
| 7   | analyze pipeline の intent_resolver LLM 統合 | analyze 自動化                     | 中   | (= 実 LLM 検証要、別セッション)          |

本セッションでは **#1-5** を順次マージする。**#6, #7 は次セッション以降**。

---

## 3. 不変条件 (= 修正で守るべきこと)

1. **OVERLAY_BACKEND=ffmpeg は完全に既存挙動を維持** (= clip_library を wire する際も
   ffmpeg backend は touch しない)
2. **旧 screenplay (= identity 無し) は無修正で動き続ける** (= clip_library lookup は
   identity が存在する場合のみ発動)
3. **AI 課金は減らす方向にしか動かない** (= clip_library wire は cold path で従来と
   同じ Imagen/Kling を呼ぶだけで、追加課金は発生させない)
4. **validator が新規拒否する場合は明確なエラーメッセージ** (= 「Phase 4 整合性
   チェックで弾かれた」が分かるように)

---

## 4. 関連ドキュメント

- `2026-05-10_compositional-architecture.md` — 設計案 (= proposal)
- `2026-05-10_parts-and-composition-overview.md` — 完成想定の図解 (= 一部は本 audit
  時点で未実現)
- `frontend/remotion/README.md` — Phase 進捗表 (= 本 audit で修正予定)
- `CLAUDE.md` — 利用可能な part categories 表 (= 修正不要、Layer 2 は完全準拠)

---

## 5. 修正履歴 (= 本 audit を起点に着手した PR)

| 日付       | 観点    | 状態    | PR                                                                                                                                  | 内容                                                                                                         |
| ---------- | ------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 2026-05-10 | 1-7     | ✅ 解消 | #131 [docs: phase status を honest 化](https://github.com/HirotakaUchishiba/short-movie-generator/pull/131)                         | README/CLAUDE.md の Phase 1 / 6 を ⚠️ skeleton に訂正                                                        |
| 2026-05-10 | 1-4     | ✅ 解消 | #132 [feat(validator): part_registry 整合性チェック](https://github.com/HirotakaUchishiba/short-movie-generator/pull/132)           | screenplay の scene_parts / global_parts id を yaml と突合検証                                               |
| 2026-05-10 | 1-3     | ✅ 解消 | #133 [feat(scene_gen): \_override\_\* fallback wiring](https://github.com/HirotakaUchishiba/short-movie-generator/pull/133)         | \_override_background_prompt / \_override_animation_prompt を採用                                            |
| 2026-05-10 | **1-1** | ✅ 解消 | #134 [feat(clip_library): scene_gen / staged_pipeline に wire](https://github.com/HirotakaUchishiba/short-movie-generator/pull/134) | satisfy_scenes_from_library + register_cold_path_clips を Stage 3/5 に hook (CLIP_LIBRARY_ENABLED で opt-in) |

### 残課題 (= 別セッション以降)

| 観点 | 内容                                                                                | 理由                                             |
| ---- | ----------------------------------------------------------------------------------- | ------------------------------------------------ |
| 1-2  | Stage 1-5 で `scene_parts` / `global_parts` を消費する機能拡張                      | 1-1 wire と整合する形で順次拡張する設計検討要    |
| 1-5  | analyze pipeline の intent_resolver LLM 統合                                        | 実 ANTHROPIC_API_KEY + 実 reference video が必要 |
| 1-6  | StageScript UI で新フィールド (= scene_parts / global_parts) を編集できるようにする | UI 設計 + part_registry catalog API の追加が必要 |
| 1-8  | e2e テスト (= identity 一致 2 screenplay の hit 検証を実 production 経路で)         | 実 AI 呼出の代替 fixture (= mock) 構築要         |

### 準拠率の変化

- **本 audit 開始時点**: 約 40-50%
- **本セッション末**: 約 70-80% (= 中核 wire と validator 整合性が動くようになった。
  UI / LLM 統合は残るが、CLI / API 経由では設計どおりに動作する)
