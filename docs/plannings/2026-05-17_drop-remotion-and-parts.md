# Remotion + 演出パーツ 完全撤去

> **作成日**: 2026-05-17
> **発端**: ユーザ要望「演出パーツを全て削除して問題ない、Remotion も不要。技術的負債を一切残さないように」
> **基本方針**: 外科的削除 (= ロールバックではなく touch-by-touch 撤去)。本 doc が削除の全体最適計画。

## WHY (= なぜやるか)

- **演出パーツ** (= scene_parts / global_parts) は `OVERLAY_BACKEND=remotion` 時のみ動画に反映されるが、既定は `ffmpeg` で auto_loop も触らないため、**本番経路では一切使われていない**
- analyze は scene_parts / global_parts を一切出力しない (= 100% 手動入力前提だが入力 UX も存在しない)
- 結果として **基盤は実装済 / データは空 / 動画にも反映されない** という三重に休眠している状態
- 演出パーツが消えれば Remotion を残す理由 (= 字幕の React 表現、effect 重畳) もすべて消える
- 残骸を抱え続けると後の改修 (= identity / casting 等) で常にノイズになるため、この機会に消し切る

## WHAT (= 撤去の全貌)

### 1. 削除する surface

| カテゴリ                                     | 対象                                                                                                                                                                                                                                                                                                                                   | 規模                                               |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| **Remotion backend**                         | `compositor_remotion.py`                                                                                                                                                                                                                                                                                                               | 583 行                                             |
| **Remotion runtime (frontend)**              | `frontend/remotion/` 配下全 34 ファイル                                                                                                                                                                                                                                                                                                | Composition / parts / components / schemas / tests |
| **OVERLAY_BACKEND dispatch**                 | `staged_pipeline.py:440` + `config.py:755-760` (3 env)                                                                                                                                                                                                                                                                                 | 〜10 行                                            |
| **render_plan API**                          | `routes/render_plan.py`                                                                                                                                                                                                                                                                                                                | 127 行                                             |
| **演出パーツ editor (frontend)**             | `ScenePartsEditor.tsx` + `GlobalPartsEditor.tsx`                                                                                                                                                                                                                                                                                       | 740 行                                             |
| **render_plan hook (frontend)**              | `useRenderPlan.ts` + test                                                                                                                                                                                                                                                                                                              | 61 行 + test                                       |
| **part_registry yaml (parts only)**          | `subtitle_styles.yaml` / `stickers.yaml` / `camera_moves.yaml` / `lower_thirds.yaml` / `transitions.yaml` / `frame_layouts.yaml` / `filter_presets.yaml` / `title_cards.yaml` (= 8 ファイル)                                                                                                                                           | yaml                                               |
| **scene_parts / global_parts schema**        | `screenplay_validator.py` schema + `_check_part_registry` の parts 分岐                                                                                                                                                                                                                                                                | 〜80 行                                            |
| **scene_parts / global_parts 型 (frontend)** | `types.ts` の `SceneParts` / `GlobalParts` / `PartReference` / `StickerPart` / `LowerThirdPart` / `SfxPart` / `GlobalPartsBgm` / `GlobalPartsCard` + `AbstractScene.scene_parts` / `AbstractScreenplay.global_parts` フィールド                                                                                                        | 〜90 行                                            |
| **テスト**                                   | `tests/test_compositor_remotion.py` (989 行) / `test_render_plan_route.py` (334 行) / `test_overlay_backend_dispatch.py` (175 行) / `test_part_registry_loader.py` (削除 or 縮小) / `test_screenplay_validator.py` の parts 部分 / `frontend/remotion/__tests__/*.test.ts` / `useRenderPlan.test.ts` / `usePartCatalog.test.ts` (縮小) | 〜1500 行 +                                        |
| **frontend deps**                            | `frontend/package.json`: `"remotion"` + `"@remotion/*"` 5 件 / `"remotion:*"` scripts 3 件                                                                                                                                                                                                                                             | json                                               |
| **routes/\_helpers.py**                      | `_ROOT_SAFE_KEYS` / `_SCENE_SAFE_KEYS` から `scene_parts` / `global_parts` を除去                                                                                                                                                                                                                                                      | 数行                                               |
| **docs (planning)**                          | `2026-05-10_compositional-architecture.md` (1364 行) / `2026-05-10_architecture-mismatch-audit.md` (229 行) / `2026-05-10_parts-and-composition-overview.md` / `2026-05-10_remotion-integration-design.md` (= 全削除)                                                                                                                  | 4 ファイル                                         |
| **docs (本体)**                              | `CLAUDE.md` の Stage 6 backend 節 + 演出パーツ表 / `docs/abstract-screenplay-design.md` の scene_parts 言及 / `docs/developments/overview.md` の Compositional Architecture 節 / 2 つの conformance audit doc の関連節                                                                                                                 | 該当節のみ                                         |

### 2. 移行する surface (= 削除しないが書き換え)

| 対象                                                               | 現状                                                                                                      | 撤去後                                                                                                                                                                                               |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`/api/parts/catalog` エンドポイント** (`routes/part_catalog.py`) | 全 9 category (parts 8 + visual_intents 1) を返す                                                         | **`/api/intent-catalog` にリネーム + visual_intents のみ返す** (= clip_library hard match の参照用)。`_INTENT_ONLY_FIELDS` filter は不要に                                                           |
| **`usePartCatalog` hook** (`frontend/src/hooks/usePartCatalog.ts`) | 全 part registry を fetch                                                                                 | **`useIntentCatalog` にリネーム + visual_intents のみ扱う**。`useCategoryEntries("subtitle_styles")` 等の他カテゴリ呼出は consumer (= ScenePartsEditor / GlobalPartsEditor) ごと削除するので問題なし |
| **`IntentCatalogPage.tsx`**                                        | usePartCatalog で全 category を表示                                                                       | useIntentCatalog に切替。表示は visual_intents のみに (= section ③ part_registry catalog の見た目がスリム化)                                                                                         |
| **`StageOverlay.tsx` の `PrimaryPreviewPanel`**                    | Remotion `<Player>` で render_plan を live preview (= platform tab で Base/Youtube/Instagram/TikTok 切替) | **既存 `output/reels_<TS>.mp4` を HTML5 `<video>` で表示する単純 preview に置き換え**。platform tab + live preview は失われる (= 後述の意図的 UX 後退)                                               |
| **`screenplay_validator.py` の `_check_part_registry`**            | scene_parts / global_parts / annotation.visual_intent_id を yaml と突合                                   | **visual_intent_id のみ突合する関数に絞る** (= 関数名は `_check_visual_intent_id` 等に rename)                                                                                                       |

### 3. 温存 (= 触らない、別系統)

- `compositor.py` (ffmpeg backend) — Stage 6 の唯一の backend として残る
- `config/part_registry/visual_intents.yaml` — Clip Library hard match key の SSOT
- `actions/` / `hooks/` / `arcs/` ディレクトリ — analyze の atomic id system (Stage 3/4)
- `subtitle_y_from_bottom` フィールド — 字幕 Y 位置の config (= 演出パーツではない、ffmpeg compositor も使う)
- `analyze/intent_resolver.py` — visual_intents の load / 突合 (= Clip Library 経路で使用)
- `clip_library.py` — identity / annotation の cache (= scene_parts と無関係)
- 直近 4 PR (= #195 - #198) の identity / casting / wardrobe 関連は全温存

### 4. 意図的に受け入れる UX 後退

- **Stage 6 の Remotion Player live preview を失う**: 「subtitles を編集 → Player で即時プレビュー」が無くなる。代わりに「再焼き直し ボタン → 出来上がった `reels_<TS>.mp4` を `<video>` で再生」になる。AI 課金は変わらない (= 再焼きは ffmpeg 1 回 = 既存挙動と同じ)
- **platform variant preview (Base/Youtube/Instagram/TikTok) を失う**: そもそも本番 publish は `output/reels_<TS>.mp4` 1 本のみで、platform variant は preview UI 内だけの mock だったため、運用上は影響なし

これらは「Remotion を消す」決定の自然な結果。本 doc 確定後に追加レビュー不要。

## HOW (= phase 分解)

7 phase、本セッション内で順次実装する (= worktree `chore/drop-remotion-and-parts` 上)。各 phase は独立 commit。

### Phase 1: Remotion backend + OVERLAY_BACKEND dispatch 削除

| 対象                                     | 操作                                                                                           |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `compositor_remotion.py`                 | 全削除                                                                                         |
| `tests/test_compositor_remotion.py`      | 全削除                                                                                         |
| `tests/test_overlay_backend_dispatch.py` | 全削除                                                                                         |
| `staged_pipeline.py:440-449`             | OVERLAY_BACKEND dispatch を削除し、ffmpeg 経路に一本化 (= `_merge_scenes` + `_apply_overlays`) |
| `config.py:755,757,759-760`              | `OVERLAY_BACKEND` / `REMOTION_CONCURRENCY` / `REMOTION_RENDER_TIMEOUT_SEC` 削除                |

検証: backend full test green。Stage 6 が ffmpeg で完結することを確認。

### Phase 2: render_plan API + StageOverlay preview 置き換え

| 対象                                               | 操作                                                                                                                                                                                                                                                  |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `routes/render_plan.py`                            | 全削除                                                                                                                                                                                                                                                |
| `preview_server.py`                                | render_plan blueprint の `register_blueprint` を削除                                                                                                                                                                                                  |
| `tests/test_render_plan_route.py`                  | 全削除                                                                                                                                                                                                                                                |
| `frontend/src/hooks/useRenderPlan.ts` + `.test.ts` | 全削除                                                                                                                                                                                                                                                |
| `frontend/src/api.ts:176-180`                      | `renderPlan()` メソッド削除。`import("../remotion/schemas/renderPlan")` 削除                                                                                                                                                                          |
| `frontend/src/components/stages/StageOverlay.tsx`  | `PrimaryPreviewPanel` を「`output/reels_<TS>.mp4` を `<video>` で再生」に書き換え。Remotion `<Player>` / `PLATFORM_COMPOSITIONS` / platform tab / `useRenderPlan` / `onPlanFps` の bubble を全削除。fps snap は const 60 (= 既存 default 維持) で代替 |

検証: frontend build + test green。Stage 6 で `<video>` preview が表示されることを確認 (= 焼き直し前は「未焼き」、後は最新 mp4)。

### Phase 3: Frontend Remotion runtime 削除

| 対象                                         | 操作                                                                                                                                                                                              |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/remotion/` ディレクトリ            | 丸ごと削除 (= Root.tsx / compositions / parts / components / schemas / **tests**、全 34 ファイル)                                                                                                 |
| `frontend/package.json`                      | dependencies から `remotion` / `@remotion/bundler` / `@remotion/cli` / `@remotion/player` / `@remotion/renderer` 削除。scripts から `remotion:studio` / `remotion:render` / `remotion:still` 削除 |
| `frontend/vite.config.*` / その他 build 設定 | remotion 関連設定があれば削除 (= 調査して該当あれば)                                                                                                                                              |

検証: `npm install` 通る、`npm run build` + `npm run test:ci` green。

### Phase 4: 演出パーツ editor + 型削除

| 対象                                                   | 操作                                                                                                                                                                                                                                                                                                    |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/components/stages/ScenePartsEditor.tsx`  | 全削除                                                                                                                                                                                                                                                                                                  |
| `frontend/src/components/stages/GlobalPartsEditor.tsx` | 全削除                                                                                                                                                                                                                                                                                                  |
| `frontend/src/components/stages/ScriptEditPanel.tsx`   | import + use (line 11-12 + line 416 + line 660) 削除                                                                                                                                                                                                                                                    |
| `frontend/src/types.ts`                                | `PartReference` / `StickerPart` / `LowerThirdPart` / `SfxPart` / `SceneParts` / `GlobalPartsBgm` / `GlobalPartsCard` / `GlobalParts` 型を削除。`AbstractScene.scene_parts` / `AbstractScreenplay.global_parts` フィールド削除。「Compositional Architecture: scene_parts のフィールド型」コメントも削除 |
| `routes/_helpers.py:92,93,99`                          | `_ROOT_SAFE_KEYS` から `scene_parts` / `global_parts` を削除、`_SCENE_SAFE_KEYS` から `scene_parts` を削除                                                                                                                                                                                              |
| `progress_store.py` / `preview_server.py` のコメント   | "scene_parts / global_parts 等" の言及を削除 (= comment update のみ)                                                                                                                                                                                                                                    |

検証: frontend build + test green。Stage 1 ScriptEditPanel が動くこと。

### Phase 5: part_registry slim + `intent_catalog` への rename

| 対象                                                                                                                                                                                               | 操作                                                                                                                                                                                           |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `config/part_registry/subtitle_styles.yaml` / `stickers.yaml` / `camera_moves.yaml` / `lower_thirds.yaml` / `transitions.yaml` / `frame_layouts.yaml` / `filter_presets.yaml` / `title_cards.yaml` | 全 8 ファイル削除                                                                                                                                                                              |
| `config/part_registry/visual_intents.yaml`                                                                                                                                                         | **温存**                                                                                                                                                                                       |
| `part_registry_loader.py`                                                                                                                                                                          | visual_intents 専用に整理 (= 全 category 列挙ロジックを単純化、または `analyze/intent_resolver.py` に統合判断)                                                                                 |
| `tests/test_part_registry_loader.py`                                                                                                                                                               | visual_intents のみテストする内容に縮小 (= or 削除して `test_intent_resolver.py` に統合)                                                                                                       |
| `routes/part_catalog.py` → `routes/intent_catalog.py` (rename)                                                                                                                                     | endpoint `/api/parts/catalog` → `/api/intent-catalog`、return は visual_intents のみ。`_INTENT_ONLY_FIELDS` filter は不要 (= 全 entry が intent) なので削除                                    |
| `preview_server.py`                                                                                                                                                                                | blueprint import / register を新名で更新                                                                                                                                                       |
| `frontend/src/hooks/usePartCatalog.ts` → `useIntentCatalog.ts` (rename)                                                                                                                            | visual_intents 専用 hook に。`useCategoryEntries` / `useCategoryStatus` の二次 API は廃止 (= 単一 category 前提なので `intentEntries` 直返しで十分)                                            |
| `frontend/src/hooks/usePartCatalog.test.ts` → 更新                                                                                                                                                 | visual_intents のみテスト                                                                                                                                                                      |
| `frontend/src/pages/IntentCatalogPage.tsx`                                                                                                                                                         | hook 切替 + section ③ の表示が visual_intents 単体になることを反映                                                                                                                             |
| `frontend/src/api.ts`                                                                                                                                                                              | `partCatalog()` → `intentCatalog()` メソッド名 + path 更新                                                                                                                                     |
| `screenplay_validator.py`                                                                                                                                                                          | SCHEMA から `scene_parts` / `global_parts` のブロック削除。`_check_part_registry` を visual_intent_id 専用に絞る (= 関数名は元のまま or `_check_visual_intent_id` に rename。後者がより明示的) |
| `tests/test_screenplay_validator.py`                                                                                                                                                               | parts 系テスト削除、visual_intent 系は残す                                                                                                                                                     |

検証: backend full test + frontend test green。IntentCatalogPage が visual_intents のみ表示することを確認。

### Phase 6: Docs cleanup

| 対象                                                                                      | 操作                                                                            |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `docs/plannings/2026-05-10_compositional-architecture.md`                                 | 全削除 (= 全面ベースの設計が撤去されたため)                                     |
| `docs/plannings/2026-05-10_architecture-mismatch-audit.md`                                | 全削除                                                                          |
| `docs/plannings/2026-05-10_parts-and-composition-overview.md`                             | 全削除                                                                          |
| `docs/plannings/2026-05-10_remotion-integration-design.md`                                | 全削除                                                                          |
| `docs/plannings/2026-05-10_full-pipeline-conformance-audit.md`                            | Compositional Architecture 関連節を削除 (= §2.6 等)                             |
| `docs/plannings/2026-05-10_full-conformance-roadmap.md`                                   | 同上                                                                            |
| `CLAUDE.md`                                                                               | Stage 6 backend dispatch 節 + 「利用可能な part categories」表 + 関連言及を削除 |
| `docs/abstract-screenplay-design.md`                                                      | scene_parts / global_parts の言及を削除 (= §3 / §9 / 派生フィールド表)          |
| `docs/developments/overview.md`                                                           | Compositional Architecture 節を削除                                             |
| **新規**: 本 doc (`2026-05-17_drop-remotion-and-parts.md`) の末尾に「実施完了」記述を追加 | 後追跡用                                                                        |

検証: `grep -rin "Compositional Architecture\|Remotion\|OVERLAY_BACKEND\|scene_parts\|global_parts" docs/ CLAUDE.md` で本 doc 自身以外残骸 0 を確認。

### Phase 7: セルフレビュー + 残骸ゼロ grep + 全テスト

| 操作                                                                                                                                           | 期待値                               |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| `pytest tests/ -q`                                                                                                                             | 0 failed                             |
| `cd frontend && npm run build`                                                                                                                 | 成功 (tsc + vite)                    |
| `cd frontend && npm run test:ci`                                                                                                               | 全 pass                              |
| `grep -rin "Remotion" --include='*.py' --include='*.ts' --include='*.tsx' --include='*.json' .`                                                | (本 doc 含む) docs/ 以外で 0 件      |
| `grep -rin "OVERLAY_BACKEND\|REMOTION_RENDER_TIMEOUT_SEC\|REMOTION_CONCURRENCY" --include='*.py' --include='*.ts' --include='*.tsx' .`         | 0 件                                 |
| `grep -rn "scene_parts\|global_parts" --include='*.py' --include='*.ts' --include='*.tsx' .`                                                   | 0 件 (= comments も含めて全削除)     |
| `grep -rn "compositor_remotion\|compose_video_remotion\|build_render_plan\|render_plan" --include='*.py' --include='*.ts' --include='*.tsx' .` | 0 件                                 |
| `grep -rn "ScenePartsEditor\|GlobalPartsEditor\|usePartCatalog\|useRenderPlan\|PartReference\|PartEntry" --include='*.ts' --include='*.tsx' .` | 0 件                                 |
| `find config/part_registry -type f`                                                                                                            | `visual_intents.yaml` 1 ファイルのみ |
| `find frontend/remotion -type f 2>/dev/null`                                                                                                   | 0 件 (= ディレクトリごと無い)        |
| 機能統合チェック: 既存の compose pipeline (analyze → compose → validator → bg_cache → kling) が動くこと                                        | 関連 unit test で確認                |

## 不変条件 (= 守るべきルール)

1. **本番動画生成 (ffmpeg compositor) は完全に不変**: 削除前後で同じ ffmpeg drawtext 経路で `overlaid.mp4` → `reels_<TS>.mp4` を生成する
2. **Clip Library (= identity / visual_intents) は触らない**: PR #195 - #197 で確立した hard match + soft rank は無変更
3. **analyze pipeline は触らない**: SYSTEM_PROMPT / location_catalog / character_catalog 連携も無変更 (= scene_parts / global_parts は最初から出力していないので削除影響なし)
4. **atomic id system (actions / hooks / arcs) は触らない**: analyze の compose ヒントとして引き続き使用
5. **subtitle_y_from_bottom は温存**: 字幕 Y 位置 config として ffmpeg compositor も既に使用
6. **削除作業は技術的負債ゼロ**: コメントの remnant、dead import、未使用型、空ファイル、stale な \_SAFE_KEYS エントリ等を残さない

## 関連ドキュメント

- `docs/plannings/2026-05-10_compositional-architecture.md` — **本機能で全削除**
- `docs/plannings/2026-05-10_clip-library-architecture.md` — Clip Library 設計 (= 別系統、温存)
- `docs/plannings/2026-05-12_legacy-schema-removal.md` — identity / annotation 自動化 (= 関係なし、温存)
- `docs/plannings/2026-05-15_auto-casting-detection.md` — casting 自動提案 (= 関係なし、温存)
- `docs/plannings/2026-05-16_wardrobe-by-location.md` — wardrobe rule (= 関係なし、温存)
- `docs/plannings/2026-05-16_restore-scene-pickers.md` — 背景/カメラ picker 復活 (= 関係なし、温存)
