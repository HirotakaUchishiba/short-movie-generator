# analyze pipeline 設計準拠アップデート計画

**日付**: 2026-05-10 (= 完了済み、PR #149-#151)
**ブランチ**: `docs/analyze-pipeline-conformance-plan` → 各 step 別ブランチへ
**設計 SSOT**: `docs/abstract-screenplay-design.md`, `CLAUDE.md`

> ⚠️ **2026-05-17 補足**: 本計画は完了している。なお当時前提だった
> 「compositional architecture (= clip_library + part_registry + Remotion)」のうち
> **Layer 2/3 (= scene_parts / global_parts / Remotion backend) は
> `2026-05-17_drop-remotion-and-parts.md` で全廃** された (= Stage 6 は
> `compositor.py` 単線、`visual_intents` のみ Clip Library cache key として残存)。
> 本ドキュメント内の Layer 2 / Remotion / scene_parts への参照は **歴史的記述** として
> 残しているが、現行コードには存在しない。

このドキュメントは「コンテキストなしの新規セッションでもこのドキュメントだけを
読めば同じパフォーマンスで実装に着手できる」状態を狙って書かれている。
監査結果の根拠 → 修正方針 → 3 ステップの段取り → 各ステップの詳細仕様 →
不変条件 → 検証戦略の順で構造化している。

---

## 1. 背景

直近 4 PR (#144〜#147) で compositional architecture (= clip_library + part_registry +
Remotion) の **inference / 描画側の負債** は片付いた。残るのは **analyze pipeline (=
参考動画 → 抽象台本 JSON の生成経路)** が新設計に準拠しているかどうか。

監査の結果、analyze pipeline は以下の状態:

- ✅ 抽象台本設計 (= `docs/abstract-screenplay-design.md`) には完全準拠
- ✅ SSOT loader (= `part_registry_loader.py`) を `intent_resolver` 経由で利用
- ✅ `clip_library.scene_has_identity` public API は route 側で利用済み
- 🔴 **identity** (`character_refs` / `location_ref` / `start_emotion` / `camera_distance`)
  が analyze 出力にも compose 出力にも入らない → `clip_library` cache hit が **構造的に
  発動しない** (= 設計が掲げたコスト削減効果の中核がオフ)
- 🔴 **annotation** (`visual_intent_id` / `duration_bucket` / `motion_intensity`) が
  analyze 出力に入らない → variant pool 内ランクの score が完全一致以外で 0 のまま
- 🟠 analyze 系 endpoint の error response が legacy `{"error": "..."}` 形式のまま
  (= Fix 2/4 で statbleished した `{error_code, message, ...}` 形式の SSOT に未追従)

`scene_parts` / `global_parts` の自動初期化は本計画の **対象外** (= UI 側で bulk apply
で吸収する Low priority、別計画で扱う)。

---

## 2. 設計準拠の判定基準 (= 着地点)

各シーンが **以下のフィールドをすべて持つ** 状態が「準拠」。空文字列ではなく
`None` / 省略のいずれでも cache hit に寄与しない。

```jsonc
{
  "scenes": [
    {
      // ── identity (= clip_library cache 鍵、Layer 1) ──
      "identity": {
        "character_refs": ["f1__office"],          // resolved ref tuple、順不同
        "location_ref": "home_office",
        "start_emotion": "中立",                    // line[0].emotion 由来
        "camera_distance": "medium-close"
      },
      // ── annotation (= variant 選択 score、Layer 1) ──
      "annotation": {
        "visual_intent_id": "talking_head_calm",   // visual_intents.yaml の id
        "duration_bucket": 5,                       // 秒単位 (5 / 10 / ...)
        "motion_intensity": "low"
      },
      // ── 既存フィールド (compose で派生) ──
      "character_refs": ["f1__office"],
      "location_ref": "home_office",
      "camera_distance": "medium-close",
      "background_prompt": "...",
      "animation_prompt": "...",
      "lines": [...]
    }
  ]
}
```

**フォールバック規約**:

- annotation は **Claude が低 confidence で返した場合** `visual_intent_id=null` を
  許容する (= novel intent fallback、scene*gen の `\_override*\*` 経路)。
- identity は **必須フィールドが揃わない場合は scene 全体に identity を付けない**
  (= `clip_library.scene_has_identity` が False を返し、cold path が走る)。

---

## 3. 修正方針 (= 3 ステップ)

### Step 1: annotation 注入 (= `intent_resolver` を analyze pipeline に wire)

**ブランチ**: `feat/analyze-annotation-injection`

**触る領域**:

- `analyze/pipeline.py` (= Claude phase 前後)
- `video_analyzer.py` (= SYSTEM_PROMPT + user content + parse 出力)
- `analyze/intent_resolver.py` (= 既存のまま、import 元を増やすだけ)
- `tests/test_analyze_pipeline_*.py` 系

**やること**:

1. `analyze/pipeline.py` の Claude 呼び出し直前で `intent_resolver.load_intent_catalog()`
   を呼び、catalog を `video_analyzer.build_screenplay()` に渡す
2. `video_analyzer.build_screenplay()` のシグネチャに `intent_catalog` を追加し、
   user content に `intent_resolver.format_catalog_for_prompt(catalog)` を inject
3. SYSTEM_PROMPT を拡張: `scenes[].annotation` を出力スキーマに追加 + 「指定の intent
   catalog から id を選び、確信が無ければ null + rationale」のルールを追記
4. Claude 出力の `scenes[].annotation` を `intent_resolver.parse_intent_assignment` で
   validate + normalize (= 未知 id は None に降格、低 confidence も None で受ける)
5. analyze の `screenplay.scenes[].annotation` フィールドに書き戻す

**やらないこと**:

- identity 生成 (= Step 2)
- `scene_parts` / `global_parts` の初期化 (= 別計画)
- `intent_resolver.detect_novel_intent_candidates` の UI 露出 (= 既存ヘルパは残すだけ、
  publish は別 issue)

**Done 基準**:

- analyze 出力の各 scene が `annotation: {visual_intent_id, duration_bucket,
motion_intensity}` を持つ (= None でも key 自体は存在)
- `clip_library.lookup_clip_pool()` が annotation 経由で score 計算する path が有効化
  (= 既存テスト `test_clip_library.py::TestAnnotationScore` の経路が analyze 出力で
  実際に発動)
- `screenplay_validator.validate_abstract` が annotation を許容するスキーマに更新
  (= 現状 additionalProperties: False で reject される可能性を確認)
- 新規 test: `tests/test_analyze_pipeline_annotation.py` で intent_resolver wire の
  end-to-end (= mock claude 戻り値で per-scene annotation が snapshot に書かれる)

**ライブ検証 (= 課金が発生)**:

- ユーザに依頼: 実 ANTHROPIC*API_KEY + 実参考動画で 1 回 analyze を実行し、生成された
  `screenplays/auto*<sha>.json` に annotation が入っているか目視確認
- コスト見積: Opus 4.7 + 100 frames + 1500 文字日本語で約 $3.30/回 (= prompt が
  1〜2 KB 増えるので $0.05 程度の上振れ、誤差レベル)

---

### Step 2: identity 派生 (= compose で生成)

**ブランチ**: `feat/analyze-identity-derivation`

**触る領域**:

- `analyze/compose.py` (= compose_screenplay が生成するシーン dict)
- `screenplay_validator.py` (= identity フィールドを許容するスキーマ拡張)
- `staged_pipeline.py` の `load_project_screenplay` 経路 (= compose が呼ばれる場所)
- `tests/test_compose_screenplay*.py` 系

**やること**:

1. `analyze/compose.py:compose_screenplay()` で、各シーンを生成する直後に
   **identity 派生ロジック** を追加する:
   ```python
   identity = {
       "character_refs": tuple(sorted(scene["character_refs"])),  # 順不同に正規化
       "location_ref": scene["location_ref"],
       "start_emotion": scene["lines"][0].get("emotion", "中立") if scene["lines"] else "中立",
       "camera_distance": scene.get("camera_distance", "medium-close"),
   }
   if all(identity.values()):  # 必須フィールドが揃った場合のみ書く
       scene["identity"] = identity
   ```
2. compose は従来通り snapshot には書かず、**呼び出された時に都度生成** する経路を
   保つ (= snapshot は abstract のまま、`load_project_screenplay` が compose 経由で
   identity / annotation 込みの完全 screenplay を返す)
3. `_override_background_prompt` / `_override_animation_prompt` が設定された scene は
   `scene_has_identity` を False にしたい (= novel intent escape hatch)。
   既存 `clip_library._scene_has_override` が満たすので、`identity` は付けても **clip
   \_library 側で bypass** される設計を確認 (= 余計な後処理は不要)
4. `screenplay_validator` の scene schema に `identity` (object, optional) を追加
5. annotation は Step 1 で abstract に既に入る → compose は **そのまま pass-through**
   (= compose では生成しない、snapshot から流す)

**やらないこと**:

- annotation の生成 (= Step 1 で済)
- clip_library への自動 register (= 既存 `register_cold_path_clips` が staged_pipeline
  の Stage 5 完了時に走るので、その経路が identity を見られるようになるだけで足りる)

**Done 基準**:

- analyze 経由で作成した project の `staged_pipeline.load_project_screenplay()` が
  返す screenplay の各 scene に `identity` が入っている (= 必須フィールドが揃った場合)
- `clip_library.scene_has_identity()` が True を返す
- `clip_library.satisfy_scenes_from_library()` が hit 可能になる (= 同 identity 持つ
  entry が library にあれば bg/kling コピーが走る)
- 新規 test: `tests/test_compose_identity.py` で identity 派生の入出力契約

**ライブ検証**:

- ユーザに依頼: 実 ANTHROPIC_API_KEY なしで、Step 1 後の analyze 結果を 1 つ取り、
  Stage 1 UI で `featured_characters` / `speaker_to_ref` / `location_ref` /
  `camera_distance` を入れた project を作成 → `GET /api/projects/<TS>/render-plan`
  または `staged_pipeline.load_project_screenplay()` の出力に identity が入っているか
  目視確認 (= API 課金なし)

---

### Step 3: error_code 統一 (= analyze 系 endpoint)

**ブランチ**: `fix/analyze-error-code-unification`

**触る領域**:

- `routes/_helpers.py` (= 共通 `api_error()` ヘルパを新設)
- `preview_server.py` の `/api/screenplay/analyze/*` 系 endpoint (= 9 endpoint)
- `frontend/src/pages/AnalyzePage.tsx` (= 動画削除の参照中検知の error_code 経由化)
- `frontend/src/components/AnalyzeJobView.tsx` (= dryrun 二重クリック検知)
- `frontend/src/api.ts` (= ApiError は既存)

**やること**:

1. `routes/_helpers.py` に `api_error(code: str, message: str, status: int, **extra)`
   を追加。戻り値は `(jsonify({...}), status)`。`code` は SCREAMING_SNAKE_CASE
   (= `ANALYZE_INVALID_SHA256` / `ANALYZE_JOB_NOT_FOUND` 等)
2. analyze 系 9 endpoint をすべて `api_error()` 経由に置き換える
3. frontend で残っている `String(e).includes(...)` / `bodyText.match(...)` を
   `e instanceof ApiError && e.body?.error_code === "..."` に置換
4. backend test を error_code assertion に更新
5. `AnalyzePage.tsx` の動画削除 409 で `body.count` を読む経路を維持 (= Fix 4 で既に
   一部対応済、analyze 系 endpoint も同じ shape で揃える)

**Done 基準**:

- `grep -r 'error_code' preview_server.py routes/` の hit が analyze 系 9 endpoint
  すべてを含む
- frontend で `includes("409")` / `bodyText.match(/(\d+)\s*件/)` が 0 件
- 既存テスト全 pass + 新規 endpoint test (= error_code を検証する追加 assertion)

**ライブ検証**:

- 不要 (= API 課金なし、ローカル dev server で挙動確認可能)

---

## 4. 不変条件 (= ステップ進行中も破ってはいけない)

| #   | 不変条件                                                                                                                                                   | なぜ                                           |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| 1   | analyze 1 回あたり Claude 呼び出しは **1 回のみ**                                                                                                          | 課金 (= $3.30/回) を増やさない                 |
| 2   | identity は scene の必須フィールド (= character_refs / location_ref / start_emotion / camera_distance) が **すべて揃った場合のみ** 書く                    | 部分 identity で誤 cache hit すると見た目崩壊  |
| 3   | annotation の `visual_intent_id` は visual_intents.yaml に存在する id か `null`、それ以外は受け取らない                                                    | `_intent_compatible` の compat lookup が壊れる |
| 4   | `_override_background_prompt` / `_override_animation_prompt` が設定された scene の identity / annotation は **clip_library で bypass** される (= 既存挙動) | novel intent escape hatch の整合性             |
| 5   | `screenplay_validator.validate_abstract` は annotation を **optional** で許容 (= 旧 abstract も読める)                                                     | 既存 project snapshot の後方互換               |
| 6   | error_code は SCREAMING_SNAKE_CASE で SSOT (= `routes/_helpers.py` 1 箇所定義)                                                                             | drift 防止                                     |

---

## 5. 検証戦略

### 自動テスト (= CI で回す)

各 step の Done 基準を pytest + vitest で satisfy する。

| Step | 新規テスト                                                                                                                                            | 既存への影響                                                                                |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 1    | `tests/test_analyze_pipeline_annotation.py` (= mock claude で annotation 出力)                                                                        | `tests/test_video_analyzer*.py` 系の SYSTEM_PROMPT 比較は Claude 出力スキーマ変更により更新 |
| 2    | `tests/test_compose_identity.py` (= compose 後の identity 派生)                                                                                       | `tests/test_compose_screenplay*.py` の構造 assertion を identity 込みに                     |
| 3    | backend `tests/test_analyze_routes.py` で error_code assertion 追加。frontend `tests/integration/AnalyzePage.test.tsx` (もし無ければ既存 test を拡張) | 既存 string match assertion を error_code に置換                                            |

### ライブ検証 (= ユーザ実行)

- Step 1 完了後: 参考動画 1 本で `python3 scripts/analyze_video.py path/to/ref.mov`
  → `screenplays/auto_<stem>.json` に annotation が入っているか目視
- Step 2 完了後: 上記 project を Stage 1 UI で完成 → `staged_pipeline.load_project_
screenplay()` 出力に identity があるか目視 (= dev server console から確認可能)
- Step 3 完了後: `curl -X POST http://localhost:5555/api/screenplay/analyze` を
  invalid sha で叩いて `error_code: "ANALYZE_INVALID_SHA256"` を返すか確認

### 失敗時のロールバック

各 step は独立した PR にする (= `gh pr merge --squash`)。失敗発覚時は revert 1 PR で
ロールバック可能。複数 step の修正を 1 PR に混ぜない (= bisect しやすく保つ)。

---

## 6. ステップ間の依存関係

```
Step 1 (annotation) ─┐
                     ├─→ ライブ検証 (= 同 video で再 analyze)
Step 2 (identity) ───┘
                     ↓
Step 3 (error_code) ── 独立 (= API shape 変更のみ、annotation/identity と無関係)
```

- Step 1 と Step 2 は **直列** (= Step 2 のテストが Step 1 の出力を前提とする)
- Step 3 は **独立** (= Step 1/2 と並行可能だが、文脈混乱を避けるため最後に着手)

---

## 7. 主要ファイル参照 (= 修正開始時に最初に開く)

### Step 1

- `/Users/hirotaka/Projects/short_movie_generator/analyze/pipeline.py:347-371` (= claude phase)
- `/Users/hirotaka/Projects/short_movie_generator/video_analyzer.py:11-80` (= SYSTEM_PROMPT)
- `/Users/hirotaka/Projects/short_movie_generator/video_analyzer.py:132-290` (= build_screenplay)
- `/Users/hirotaka/Projects/short_movie_generator/analyze/intent_resolver.py:99-203` (= load + format)
- `/Users/hirotaka/Projects/short_movie_generator/analyze/intent_resolver.py:206-282` (= parse)
- `/Users/hirotaka/Projects/short_movie_generator/screenplay_validator.py` の `validate_abstract`

### Step 2

- `/Users/hirotaka/Projects/short_movie_generator/analyze/compose.py:177-258` (= compose_screenplay)
- `/Users/hirotaka/Projects/short_movie_generator/clip_library.py:308-336` (= \_scene_to_identity)
- `/Users/hirotaka/Projects/short_movie_generator/staged_pipeline.py` の `load_project_screenplay`
- `/Users/hirotaka/Projects/short_movie_generator/screenplay_validator.py` の scene schema

### Step 3

- `/Users/hirotaka/Projects/short_movie_generator/routes/_helpers.py` (= api_error 追加先)
- `/Users/hirotaka/Projects/short_movie_generator/preview_server.py:748-945` (= 9 endpoint)
- `/Users/hirotaka/Projects/short_movie_generator/frontend/src/pages/AnalyzePage.tsx`
- `/Users/hirotaka/Projects/short_movie_generator/frontend/src/components/AnalyzeJobView.tsx`
- `/Users/hirotaka/Projects/short_movie_generator/frontend/src/api.ts` (= ApiError は既存)

---

## 8. SSOT 配置確認 (= 直近 Fix 2 の結果)

以下は **既に修正済み** で、本計画では再修正しない。Step 1〜3 でこれらを **utilize する**:

- `part_registry_loader.py` — `intent_resolver.load_intent_catalog()` が経由
- `clip_library.scene_has_identity` — public API
- `clip_library._scene_has_override` — bypass 判定共通ヘルパ
- `clip_library.register_clip_entry` — atomic write (.tmp + os.replace)
- `frontend/src/api.ts` の `ApiError` class — Step 3 で全面利用

---

## 9. 既知の宿題 (= 本計画では扱わない)

- `scene_parts` / `global_parts` の自動初期化 (= UI で bulk apply で吸収する Low)
- ✅ `analyze/compose.py` で scene_parts / global_parts が silent strip される問題 → **解消済**
  (= PR #157 で `compose_screenplay()` を `dict(abstract)` 起点の pass-through contract に統一)
- ✅ `intent_resolver.detect_novel_intent_candidates` の UI 露出 → **解消済**
  (= PR #156 で SSE event に annotation_stats を含めて UI 表示、PR #165 で save phase
  に `_collect_novel_intent_candidates()` を組み込み novel_intent_candidates を出力)
- 同 video_sha 再 analyze 時の template 上書き警告 (= UI 改修、Low)

### 設計外の追加実装 (= 本計画策定時には未予定だった enhancement)

| 追加                                | 場所                                                                             | 設計 doc 反映                                            |
| ----------------------------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `annotation.confidence` (0.0-1.0)   | `video_analyzer.py` SYSTEM_PROMPT + `intent_resolver.normalize_scene_annotation` | `docs/abstract-screenplay-design.md` §2 / §3 B' に追記済 |
| `annotation.rationale` (string)     | 同上                                                                             | 同上                                                     |
| `novel_intent_candidates` SSE event | `analyze/pipeline.py:_collect_novel_intent_candidates()`                         | 同上 (= cold path 説明)                                  |

---

## 10. 進捗トラッキング

- [x] Step 0: 本ドキュメント (= main マージ済)
- [x] Step 1: annotation 注入 (= `feat/analyze-annotation-injection`、PR #149)
- [x] Step 2: identity 派生 (= `feat/analyze-identity-derivation`、PR #150)
- [x] Step 3: error_code 統一 (= `fix/analyze-error-code-unification`、PR #151)

各 step PR には本ドキュメントへのリンクを必ず含める (= 後追いで context が再現できる
ように)。
