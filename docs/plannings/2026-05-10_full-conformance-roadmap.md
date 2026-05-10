# analyze pipeline 100% 設計準拠ロードマップ

**日付**: 2026-05-10
**前提**: PR #149 / #150 / #151 (= Step 1〜3) merge 済み + ライブ検証 PASS
**設計 SSOT**: `docs/plannings/2026-05-10_compositional-architecture.md`,
`docs/abstract-screenplay-design.md`, `CLAUDE.md`
**監査 source**: `docs/plannings/2026-05-10_analyze-pipeline-conformance.md` (= Step 1〜3 計画) +
本ロードマップ作成時の追加監査 (= 21 gap 同定)

このドキュメントは「コンテキストなしの新規セッションでもこのドキュメントだけを
読めば 100% 準拠への残作業を同等パフォーマンスで実行できる」状態を狙う。

---

## 1. 現状サマリ

Step 1〜3 で以下を達成:

- ✅ Layer 1 identity 派生 (= compose で生成、live 17/17 で確認)
- ✅ Layer 1 annotation 注入 (= intent_resolver wire、live 17/17 で確認)
- ✅ error_code 統一 (= 10/10 endpoint で SCREAMING_SNAKE_CASE)

しかし **Critical 級の漏れ** が後発で 1 件、追加監査で関連 20 件が判明:

### Critical 漏れの実証

`compose_screenplay()` に scene_parts / global_parts 入りの abstract を渡した結果:

```
=== compose 後 root keys ===     ['caption', 'scenes']
=== compose 後 scene[0] keys === ['animation_prompt', 'background_prompt',
                                  'character_refs', 'characters', 'duration',
                                  'identity', 'lines', 'lipsync', 'location_ref']
global_parts pass-through?: False
scene_parts pass-through?: False
```

つまり Layer 2 (= scene_parts / global_parts) **すべてのカテゴリ**が Stage 6 に届かない。
原因は `analyze/compose.py:compose_screenplay()` の **出力起点が新規 dict**
で、明示転記したキーしか引き継がない実装にある。

### 連鎖して落ちる他のフィールド

追加監査で同じ silent strip 経路で落ちることが判明:

- root: `featured_characters` / `speaker_to_ref` / `subtitle_y_from_bottom` /
  `hook_id` / `arc_id` / `global_parts`
- scene: `scene_parts` / `action_id` / 旧 alias (start_emotion / visual_intent_id /
  duration_bucket / motion_intensity の flat)

これにより Stage 3/4 の atomic id 経路 (`scene_gen` の action_id 解決)、
Stage 6 の subtitle_y_from_bottom / scene_parts / global_parts、
clip_library の variant 多様性 (= flat alias 経由) 等が **すべて無効化されている**。

---

## 2. 修正後の不変条件 (= 100% 準拠の定義)

| #   | 不変条件                                                                                                    | 検証方法                                                      |
| --- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| 1   | `compose_screenplay()` は **派生フィールドを追加** するだけで abstract の他キーは破壊しない                 | tests/test_analyze_compose.py::TestNonDerivedFieldPassThrough |
| 2   | snapshot に書いた `scene_parts.subtitle_style.id` が `GET /api/projects/<TS>/render-plan` の plan に届く    | tests/test_render_plan_route.py に E2E 追加                   |
| 3   | snapshot に書いた `global_parts.filter_preset.id` が render_plan に届く                                     | 同上                                                          |
| 4   | snapshot に書いた `subtitle_y_from_bottom` が ffmpeg / Remotion 双方の出力に反映される                      | unit test 既存 + E2E 追加                                     |
| 5   | abstract に書いた `action_id` が scene_gen の prompt 派生に反映される                                       | tests/test_scene_gen に E2E                                   |
| 6   | `_override_*` フィールドは `null` 値も保持される (validator schema と整合)                                  | unit test 追加                                                |
| 7   | identity の必須フィールド集合 (= 4 fields) と validator schema (= 3 fields required) の不整合解消           | schema fix + 既存 test 更新                                   |
| 8   | `_SCENE_PART_FIELDS_*` / `_GLOBAL_PART_FIELDS` のカテゴリ集合が `KNOWN_CATEGORIES` と drift しない          | 新規 drift 監査 test                                          |
| 9   | annotation の `visual_intent_id` の `valid_start_emotions` 制約が validator で check される                 | unit test + 既存 test 更新                                    |
| 10  | UI に identity / annotation 編集 component が存在する                                                       | frontend test                                                 |
| 11  | analyze 完了後の SSE event に annotation_stats (assigned / low_confidence) が乗る                           | analyze pipeline 統合 test                                    |
| 12  | `routes/clip_library.py` の snapshot 直読み workaround が削除され、`load_screenplay_for_project` 経由に統一 | grep で workaround 0 件                                       |

---

## 3. Phase 構造 (= 並行性で束ねる)

### Phase A: compose pass-through contract (= 直列必須、最重要)

**ブランチ**: `feat/compose-passthrough-contract`
**worktree**: `~/Projects/swmg-worktrees/phase-a-compose/`
**着手**: 直 (= 他に依存無し)
**解決する gap**: G-1 (compose strip) + G-17 (test 網羅)
**間接解消する gap**: G-2 (subtitle_y), G-3 (action_id), G-5 (featured_characters/speaker_to_ref),
G-11 (annotation flat alias), G-12 (clip_library 経由), G-13 (workaround 解消可能), G-19 (doc 同期), G-20 (audit doc 追記)

**実装方針**:

1. `compose_screenplay()` の出力 dict 起点を `dict(abstract)` (= shallow copy) に変更
2. scenes も `dict(src)` で開始し、派生キー (background_prompt / animation_prompt /
   character_refs / characters / lipsync / line.speaker / line.voice_overrides /
   identity / 必要なら annotation pass-through) を **追記/上書き** する形に
3. 旧明示転記 (= `sp = {"caption": ..., "scenes": []}`) は削除
4. tests/test_analyze_compose.py に `TestNonDerivedFieldPassThrough` クラスを追加。
   各非派生フィールドごとに 1 test (= 8 件: featured_characters / speaker_to_ref /
   subtitle_y_from_bottom / hook_id / arc_id / global_parts / scene_parts / action_id +
   旧 alias 4 件)
5. 既存 TestAnnotationPassThrough / TestOverridePassThrough / TestIdentityDerivation
   は契約変更で挙動が変わる可能性あるので **同 PR で更新**
6. docs/abstract-screenplay-design.md §3 / §6 に「pass-through 契約」段落追加

**Done 基準**:

- `python3 -c "..."` で abstract 入力 → compose 出力に上記全フィールドが残ることを実証
- backend tests 全 pass (= 既存 1429 + 新規 ~10)
- frontend tests / tsc 影響なし

### Phase B: render_plan E2E 検証 (= Phase A 後に直列)

**ブランチ**: `test/render-plan-parts-e2e`
**worktree**: `~/Projects/swmg-worktrees/phase-b-render-e2e/`
**着手**: Phase A merge 後
**解決する gap**: G-6 (= 念のための整合確認) + G-18 (E2E test 追加)

**実装方針**:

1. `tests/test_render_plan_route.py` に新規 test:
   - snapshot に `scene_parts.subtitle_style = {id: "karaoke_bold"}` 入れて project 作成
   - Stage 5 完了状態を mock (= scene\_<S>.mp4 を tmp に置く)
   - `GET /api/projects/<TS>/render-plan` を叩く
   - `plan.scenes[0].parts.subtitle_style.id == "karaoke_bold"` を assert
2. `global_parts.filter_preset` も同様に E2E
3. `subtitle_y_from_bottom` も同様に E2E

**Done 基準**:

- 新規 E2E test 3 件 pass

### Phase C: 並行可能な独立修正 (= Phase A と並行可)

各 worktree は独立、Phase A の出力に依存しない。

#### Phase C1: `_override_*` null 受入

**ブランチ**: `fix/compose-override-null-passthrough`
**worktree**: `~/Projects/swmg-worktrees/phase-c1-override-null/`
**解決する gap**: G-4

**実装方針**: `analyze/compose.py:245-248` の `isinstance(v, str) and v.strip()` を
緩めて null 値も保持する。または Phase A の dict(src) 起点で自動解決するなら C1 は
吸収される。Phase A 完了後に「未解決か」を判定して必要なら別 PR。

#### Phase C2: Stage 6 fallback debug log

**ブランチ**: `chore/stage6-fallback-debug-log`
**worktree**: `~/Projects/swmg-worktrees/phase-c2-fallback-log/`
**解決する gap**: G-7

**実装方針**: `compositor_remotion._scene_subtitle_style_part` で scene_parts.subtitle_style
が無い時に `logger.debug("subtitle_style 未指定 → minimal を採用")` を 1 行追加。

#### Phase C3: validator parts 強化

**ブランチ**: `feat/validator-parts-strict-checks`
**worktree**: `~/Projects/swmg-worktrees/phase-c3-validator/`
**解決する gap**: G-8 + G-9 + G-10

**実装方針**:

1. tests/test*screenplay_validator.py に「`\_SCENE_PART_FIELDS*\*`の category 集合 ⊆`KNOWN_CATEGORIES`」drift 監査 test
2. identity.required に "camera_distance" を追加 + 既存 test 修正
3. `_check_part_registry` に visual_intents.yaml の `valid_start_emotions` 制約 check 追加

#### Phase C4: UI で identity / annotation 編集

**ブランチ**: `feat/ui-identity-annotation-editors`
**worktree**: `~/Projects/swmg-worktrees/phase-c4-ui-editors/`
**解決する gap**: G-14

**実装方針**:

1. `frontend/src/components/IdentityEditor.tsx` を新設 (= character_refs / location_ref /
   start_emotion / camera_distance を per-scene で編集)
2. `frontend/src/components/AnnotationEditor.tsx` を新設 (= visual_intent_id /
   duration_bucket / motion_intensity を per-scene で編集、catalog は usePartCatalog 経由)
3. `ScriptEditPanel.tsx` から呼び出し
4. vitest で編集 → onChange 経路をテスト

#### Phase C5: analyze SSE に annotation_stats を emit

**ブランチ**: `feat/analyze-sse-annotation-stats`
**worktree**: `~/Projects/swmg-worktrees/phase-c5-sse-stats/`
**解決する gap**: G-15

**実装方針**:

1. `analyze/pipeline.py` の `phase_complete:save` で annotation を集計
   (= assigned / low_confidence / by_intent_id) して event に乗せる
2. `frontend/src/components/AnalyzeJobView.tsx` に表示
3. analyze pipeline test に統計 assertion を追加

### Phase D: 任意 / 後回し

- **G-16**: scene_parts 変更時の approval 部分保持 (= UX 改善、設計範囲外)
- **G-21**: novel intent suggestion 全経路 (= 別セッション、実 LLM 検証要)

---

## 4. 並行実行戦略 (= git worktree 配置)

```
~/Projects/short_movie_generator/                  # main worktree (= main branch)
~/Projects/swmg-worktrees/
  ├── phase-a-compose/                              # feat/compose-passthrough-contract
  ├── phase-b-render-e2e/                           # test/render-plan-parts-e2e
  ├── phase-c1-override-null/                       # fix/compose-override-null-passthrough
  ├── phase-c2-fallback-log/                        # chore/stage6-fallback-debug-log
  ├── phase-c3-validator/                           # feat/validator-parts-strict-checks
  ├── phase-c4-ui-editors/                          # feat/ui-identity-annotation-editors
  └── phase-c5-sse-stats/                           # feat/analyze-sse-annotation-stats
```

worktree 作成例:

```bash
mkdir -p ~/Projects/swmg-worktrees
git worktree add ~/Projects/swmg-worktrees/phase-a-compose -b feat/compose-passthrough-contract
```

実行順序:

```
時刻 0:    Phase A 着手 (= 直列必須、Phase B/C のすべてに影響)
時刻 0:    Phase C1, C2, C3, C4, C5 を 5 並行 worktree で着手 (= Phase A と独立)
時刻 +1:   Phase A merge → Phase B 着手
時刻 +N:   各 Phase merge 完了で main に集約
```

各 worktree は独立 git index を持つので、同時 commit / push / PR 作成が可能
(= ファイル衝突は最終 merge 時の rebase で解消)。

---

## 5. ロールバック / 衝突解決

- 各 phase は独立 PR (= squash merge) → revert 1 PR で局所ロールバック可能
- Phase A と Phase C1 が同じ `analyze/compose.py` を触るため、Phase A の merge 後に
  C1 の有効性を再判定 (= 吸収されていれば C1 を close)
- Phase A と Phase C3 / C4 / C5 はファイル衝突なし (= 並行 merge 可)
- Phase B は Phase A merge を **必須前提** とする (= 鎖 1 本)

---

## 6. Done 基準 (= 100% 準拠の確認手順)

すべての phase merge 後に以下を順番に実行:

```bash
# 1. backend tests
cd ~/Projects/short_movie_generator
python3 -m pytest tests/ -q

# 2. frontend tests + tsc
cd frontend
npx tsc --noEmit
npx vitest run

# 3. compose pass-through 実証
python3 -c "
import sys; sys.path.insert(0, '.')
from analyze.compose import compose_screenplay
abstract = {
    'caption': 'x', 'featured_characters': ['f1'],
    'subtitle_y_from_bottom': 800,
    'global_parts': {'filter_preset': {'id': 'warm_cinematic'}},
    'scenes': [{
        'duration': 5, 'location_ref': 'home_office', 'action_id': 'desk_typing',
        'scene_parts': {'subtitle_style': {'id': 'karaoke_bold'}},
        'lines': [{'text': 'x', 'start': 0, 'end': 1, 'emotion': '中立'}],
    }],
}
sp = compose_screenplay(abstract)
assert sp['subtitle_y_from_bottom'] == 800, '❌ G-2'
assert sp['global_parts']['filter_preset']['id'] == 'warm_cinematic', '❌ G-1'
assert sp['scenes'][0]['scene_parts']['subtitle_style']['id'] == 'karaoke_bold', '❌ G-1'
assert sp['scenes'][0]['action_id'] == 'desk_typing', '❌ G-3'
print('✅ pass-through OK')
"

# 4. render_plan E2E (= Phase B test が pass すれば自動)
python3 -m pytest tests/test_render_plan_route.py -q

# 5. drift 監査 (= Phase C3 test が pass すれば自動)
python3 -m pytest tests/test_screenplay_validator.py -q
```

すべて pass + 上記 100% 準拠の不変条件 12 件が assert される状態 = 完了。

---

## 7. 主要ファイル参照

### Phase A

- `/Users/hirotaka/Projects/short_movie_generator/analyze/compose.py:177-282` (= compose_screenplay)
- `/Users/hirotaka/Projects/short_movie_generator/tests/test_analyze_compose.py` (= 既存テスト + 追加)
- `/Users/hirotaka/Projects/short_movie_generator/docs/abstract-screenplay-design.md` (= 契約 doc 化)

### Phase B

- `/Users/hirotaka/Projects/short_movie_generator/tests/test_render_plan_route.py`
- `/Users/hirotaka/Projects/short_movie_generator/routes/render_plan.py`

### Phase C1

- `/Users/hirotaka/Projects/short_movie_generator/analyze/compose.py:245-248`

### Phase C2

- `/Users/hirotaka/Projects/short_movie_generator/compositor_remotion.py:204-210`

### Phase C3

- `/Users/hirotaka/Projects/short_movie_generator/screenplay_validator.py:75-84, 204-208, 257-265, 555-573, 627-690`
- `/Users/hirotaka/Projects/short_movie_generator/tests/test_screenplay_validator.py`
- `/Users/hirotaka/Projects/short_movie_generator/part_registry_loader.py` (= KNOWN_CATEGORIES)

### Phase C4

- `/Users/hirotaka/Projects/short_movie_generator/frontend/src/components/stages/ScriptEditPanel.tsx`
- `/Users/hirotaka/Projects/short_movie_generator/frontend/src/hooks/usePartCatalog.ts`
- 新規: `/Users/hirotaka/Projects/short_movie_generator/frontend/src/components/IdentityEditor.tsx`
- 新規: `/Users/hirotaka/Projects/short_movie_generator/frontend/src/components/AnnotationEditor.tsx`

### Phase C5

- `/Users/hirotaka/Projects/short_movie_generator/analyze/pipeline.py:380-411` (= save phase)
- `/Users/hirotaka/Projects/short_movie_generator/frontend/src/components/AnalyzeJobView.tsx`
- `/Users/hirotaka/Projects/short_movie_generator/analyze/intent_resolver.py` (= detect_novel_intent_candidates)

---

## 8. 進捗トラッキング (= phase 完了で check)

- [ ] Phase A: compose pass-through contract (`feat/compose-passthrough-contract`)
- [ ] Phase B: render_plan E2E (`test/render-plan-parts-e2e`) — A 完了後
- [ ] Phase C1: override null 受入 (`fix/compose-override-null-passthrough`)
- [ ] Phase C2: Stage 6 fallback debug log (`chore/stage6-fallback-debug-log`)
- [ ] Phase C3: validator parts 強化 (`feat/validator-parts-strict-checks`)
- [ ] Phase C4: UI identity/annotation editors (`feat/ui-identity-annotation-editors`)
- [ ] Phase C5: analyze SSE annotation stats (`feat/analyze-sse-annotation-stats`)
- [ ] Phase D-G16: scene_parts approval 部分保持 (= optional)
- [ ] Phase D-G21: novel intent suggestion 全経路 (= 別セッション)

各 phase PR 説明には本 doc へのリンクを含める。
