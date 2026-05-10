# 2026-05-10: novel intent suggestion を UI 経由でシームレスに catalog に取り込むフロー

## 0. 背景

### 0.1 現状

`analyze` pipeline は `confidence < 0.7` が連続するシーン群を novel intent 候補として検出し、`<screenplay>.suggested_intents.json` に書き出している (`analyze/pipeline.py:514`)。`AnalyzeJobView` は SSE event `suggested_intents` を受けて画面下部に **件数 + IntentCatalog へのリンク** を表示する (`AnalyzeJobView.tsx:654-670`)。

しかし以下の gap がある:

| gap                            | 影響                                                                                                             |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| 候補の中身が UI から見えない   | proposed_id / description / rationale を確認するには `screenplays/*.suggested_intents.json` を直接開く必要がある |
| トリアージ状態が永続化されない | 「却下した」「採用予定」「PR 作成済み」が track できず、同じ候補が analyze 実行ごとに再提示される                |
| プロジェクト横断の集約がない   | 各 analyze 実行が個別ファイルを書く。同じ proposed_id が複数プロジェクトで出ても dedupe / 頻度集計されない       |
| catalog 反映までの摩擦が大きい | `visual_intents.yaml` の entry 構造を覚えて手書き → PR → `grow_clip_pool.py` の手順が運用者の認知負荷            |

### 0.2 解きたい問題

**「analyze pipeline が検出した novel intent を、UI 上で 1 画面でトリアージ → 採用 → PR テンプレ生成 → catalog 反映 まで運べる」** 状態にする。

### 0.3 守るべき不変条件

| 不変条件                                                            | 理由                                                                    |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `visual_intents.yaml` への自動書き込みは禁止                        | 粒度の一貫性が崩れると cache hit 率が低下する。catalog はガバナンス対象 |
| `_override_*` 経路は廃止しない                                      | 緊急 cold path。本フロー導入後も常に動く                                |
| 既存 `<screenplay>.suggested_intents.json` 読み込み path は当面残す | 進行中 analyze job の途中破壊を避ける (= migration 期は両 write)        |
| analyze pipeline 側のシグネチャ変更は最小に                         | `_collect_novel_intent_candidates()` の出力契約を変えない               |

## 1. スコープ

### 1.1 in scope

- `data/intent_suggestions.json` (= aggregated inbox) の追加
- `analyze/pipeline.py` の save phase での upsert 経路追加 (= 既存 single-file write は migration 期だけ並行)
- `routes/intent_suggestions.py` (= 一覧 / mark-reviewing / dismiss / accept / yaml snippet 生成)
- `IntentCatalogPage.tsx` への `IntentSuggestionsSection` 追加 (= 最上段)
- `AnalyzeJobView.tsx` のリンクを `/intent-catalog#suggestions` に変更
- merged 自動検出 (= `visual_intents.yaml` に該当 id が登場したら status を `merged` に遷移)
- 既存 `screenplays/*.suggested_intents.json` を inbox に吸い上げる migration script

### 1.2 out of scope

- catalog yaml への自動書き込み (= ガバナンス維持のため意図的に除外)
- novel intent 提案アルゴリズムの改良 (= `detect_novel_intent_candidates` の閾値・連続条件等は触らない)
- `grow_clip_pool.py` の自動キック (= 採用後の variant 構築は手動コマンドのまま)
- `visual_intents` 以外のカテゴリ (= `subtitle_styles` 等) への拡張
- 候補の中身に thumbnail を載せる (= scene_indices と reference video の紐付けは別 issue)

## 2. データモデル

### 2.1 IntentSuggestionRecord (= inbox の 1 行)

```python
@dataclass
class IntentSuggestionRecord:
    id: str                       # sha256(proposed_id + description.strip())[:16]
    proposed_id: str              # detect_novel_intent_candidates の出力
    description: str
    rationale: str
    scene_indices: tuple[int, ...]
    source_screenplay: str        # screenplays/auto_<sha>.json (= 最後に検出された source)
    source_analyze_job_id: str | None
    status: SuggestionStatus      # new | reviewing | accepted | dismissed | merged
    dismissed_reason: str | None
    occurrences: int              # 同 id が再検出された累計回数 (= 採用優先度シグナル)
    created_at: str               # ISO8601 (= 初回検出)
    updated_at: str               # ISO8601 (= 直近 upsert / status 変更)
```

`id` は `proposed_id + description` の hash で算出することで、同じ意味の候補が再検出されたとき dedupe できる。occurrences はそのカウンタ。

### 2.2 SuggestionStatus と遷移

```
[analyze 完了]
    │ upsert
    ▼
   new ──[マークレビュー中]──▶ reviewing
    │                            │
    │ [却下]                     │ [採用]
    ▼                            ▼
dismissed                     accepted
                                 │
                                 │ (= visual_intents.yaml に同 id 出現を polling 検知)
                                 ▼
                              merged
```

| status      | 意味                                     | 次の遷移先                                        |
| ----------- | ---------------------------------------- | ------------------------------------------------- |
| `new`       | 検出されたばかり、未トリアージ           | reviewing / dismissed / accepted                  |
| `reviewing` | 運用者が検討中                           | dismissed / accepted                              |
| `dismissed` | 採用しないと判断 (= reason 必須)         | (= 終端、ただし occurrences が増えれば再浮上候補) |
| `accepted`  | yaml に追加予定 (= snippet をコピー済み) | merged                                            |
| `merged`    | yaml に entry が反映された (= 自動検出)  | (= 終端)                                          |

### 2.3 永続化先

`data/intent_suggestions.json` (= 単一 JSON、entry のリスト)。

採用理由:

| 候補                                 | 採否    | 理由                                                                                      |
| ------------------------------------ | ------- | ----------------------------------------------------------------------------------------- |
| 単一 JSON ファイル                   | ✅ 採用 | 規模が小さい (= 数十〜百 entry) / 直接 inspect 可能 / 必要なら gitignore 解除で履歴追跡可 |
| JSONL (append-only)                  | ❌      | status 更新で rewrite 必要なので append-only の利点が消える                               |
| SQLite (`analytics.db` 等への相乗り) | ❌      | 用途が違う (= 運用ダッシュボード vs 投稿成績) / マイグレーション複雑化                    |
| ディレクトリ + 1 entry 1 file        | ❌      | clip_library と粒度が違う / overkill                                                      |

同時書き込みリスク: `preview_server` は単一 process。fcntl ロックで十分。

## 3. API 設計 (= `routes/intent_suggestions.py`)

| method | path                                          | request                                                     | response                                                             |
| ------ | --------------------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------- |
| GET    | `/api/intent-suggestions?status=<filter>`     | filter ∈ {all, new, reviewing, dismissed, accepted, merged} | `{ entries: IntentSuggestionRecord[], counts: {<status>: int} }`     |
| POST   | `/api/intent-suggestions/<id>/mark-reviewing` | (なし)                                                      | `{ ok: true, record: IntentSuggestionRecord }`                       |
| POST   | `/api/intent-suggestions/<id>/dismiss`        | `{ reason: string }` (= 必須、空文字拒否)                   | `{ ok: true, record: IntentSuggestionRecord }`                       |
| POST   | `/api/intent-suggestions/<id>/accept`         | (なし)                                                      | `{ ok: true, record: IntentSuggestionRecord, yaml_snippet: string }` |
| GET    | `/api/intent-suggestions/<id>/yaml`           | (なし)                                                      | text/yaml: snippet (= 再取得用)                                      |

`merged` への遷移は GET 一覧の応答時に `visual_intents.yaml` を読み、`proposed_id` が yaml に存在する `accepted` entry を `merged` に **遅延更新** する (= yaml は別 process / PR で書き換わる前提)。

### 3.1 yaml snippet 生成

`accept` 応答に含まれる `yaml_snippet` の例:

```yaml
- id: proposed_frantic_typing_at_desk
  description: |
    # rationale を 1-2 行に要約。運用者が手で整える前提
    {{rationale_summary}}
  suggested_kling_template: |
    # TODO: 運用者が記述
    A {character} {pose_modifier} in {location_decor},
    {start_emotion_addon}, ...
  duration_buckets: [5, 10] # 推定値、要調整
  valid_start_emotions: [] # TODO: 要記述
  motion_intensity_bucket: medium # rationale から推定 (= 要確認)
  pool_target_size: 8
  compatible_with: []
  deprecated: false
```

不変条件: **すべての必須フィールドを埋めるところまで自動化しない**。粒度判断は人間に委ねる (= `# TODO` で明示)。

### 3.2 エラーハンドリング

| 状況                                         | レスポンス                                                         |
| -------------------------------------------- | ------------------------------------------------------------------ |
| 不正 status 遷移 (= dismissed → accepted 等) | 409 Conflict + 現在 status                                         |
| 存在しない id                                | 404                                                                |
| dismiss に reason 空文字                     | 400 + バリデーションメッセージ                                     |
| inbox file 破損                              | 500 + log。`data/intent_suggestions.errors.log` にスタックトレース |

## 4. UI 設計 (= `IntentCatalogPage.tsx`)

### 4.1 セクション順序

```
🗂 Intent Catalog
├── 💡 提案中の novel intent (= 新セクション、最上段) ← 追加
├── 📦 clip_library entries (= 既存)
└── 🎨 part_registry (= 既存)
```

最上段に置く理由: catalog 拡張は基本的に「提案 → 採用 → PR」の 1 方向フローで、毎回最初に確認すべき情報だから。

### 4.2 IntentSuggestionsSection

カード一覧 + status フィルタ。フィルタは clip_library と同じデザイン言語:

```
[all] [new] [reviewing] [accepted] [dismissed] [merged]
```

各カード:

```
┌─────────────────────────────────────────────────┐
│ proposed_frantic_typing_at_desk  [new] [×3]     │
│ ─────────────────────────────────────────────── │
│ description: ...                                │
│ rationale:   ...                                │
│ scenes:      [3, 7]  (auto_xyz.json)            │
│ ─────────────────────────────────────────────── │
│ [✏️ レビュー中にする]  [📋 yaml snippet 取得]   │
│ [❌ 却下]                                       │
└─────────────────────────────────────────────────┘
```

| 要素                    | 仕様                                                                                                |
| ----------------------- | --------------------------------------------------------------------------------------------------- |
| `[new]` バッジ          | status を色分け (= new=blue / reviewing=amber / accepted=emerald / dismissed=slate / merged=violet) |
| `[×3]` バッジ           | `occurrences > 1` のときのみ表示。「3 回提案された」= 採用優先度高                                  |
| description / rationale | inline 表示 (= scroll せずに見える)                                                                 |
| `scenes:`               | scene_indices + source_screenplay (= analyze job 詳細へリンク)                                      |
| ボタン群                | status により表示 / 非表示を切り替え (= 終端 status はボタン無し)                                   |

### 4.3 yaml snippet コピー UX

「📋 yaml snippet 取得」 click 時:

1. `POST /api/intent-suggestions/<id>/accept` を呼ぶ
2. レスポンスの `yaml_snippet` を:
   - clipboard にコピー (= `navigator.clipboard.writeText`)
   - カード内に折り畳み式 inline preview として表示 (= もう一度コピー可)
3. toast で通知:
   ```
   snippet をコピーしました。
   config/part_registry/visual_intents.yaml に貼り付け、
   PR を作成してください。
   ```
4. status は `accepted` に遷移 (= バッジ色も切り替わる)

### 4.4 dismiss UX

「❌ 却下」 click 時:

1. `window.prompt("却下理由 (= 後で見直すため必須):")` で reason 入力
2. 空文字なら何もしない (= キャンセル扱い)
3. `POST /api/intent-suggestions/<id>/dismiss` を呼ぶ
4. status を `dismissed` に切り替え、reason をカードに表示

### 4.5 AnalyzeJobView との連携

```tsx
// before
<Link to="/intent-catalog">💡 新規 intent 候補 N 件</Link>

// after
<Link to="/intent-catalog#suggestions">💡 新規 intent 候補 N 件</Link>
```

`IntentCatalogPage` 側で `useEffect` で `location.hash === "#suggestions"` を検知し、IntentSuggestionsSection に scrollIntoView する。

## 5. analyze pipeline 側の変更

`analyze/pipeline.py:save phase` (= line 510-540 周辺) の差分:

| 旧                                                | 新 (= migration 期)                            | 新 (= migration 完了後)                 |
| ------------------------------------------------- | ---------------------------------------------- | --------------------------------------- |
| `<output_path>.suggested_intents.json` に直接書く | 同左 + `suggestion_store.upsert(records)` 並行 | `suggestion_store.upsert(records)` のみ |
| SSE event の payload は `suggested_intents` キー  | 同左 (= UI 互換維持)                           | 同左                                    |

### 5.1 既存 SSE event payload は変えない

`AnalyzeJobView.tsx:220` は `d.phase === "save" && Array.isArray(d.suggested_intents)` を見ているので、**event 構造を変えない**。UI 側のリンク先 anchor 追加だけで済む。

### 5.2 並行 write の終了条件

Phase 4 で migration が完了したら個別 JSON 書き込みを削除。それまでは:

- 既存 `<screenplay>.suggested_intents.json` を読む code はテストにしか存在しない (= 確認済み、production read path はゼロ)
- 並行 write のコストは数十バイト × 数 entry → 無視可

## 6. 実装タスク

### Phase 1: 永続化レイヤ (= 1-2 日)

- [ ] `analyze/suggestion_store.py` 新規追加
  - [ ] `IntentSuggestionRecord` dataclass + `SuggestionStatus` Enum
  - [ ] id 算出ロジック (= `sha256(proposed_id + description.strip())[:16]`)
  - [ ] `load() -> list[IntentSuggestionRecord]`
  - [ ] `upsert(records: list[IntentSuggestionRecord])` — id 一致で `updated_at` + `occurrences` 更新、新規なら append
  - [ ] `update_status(id, status, reason=None)` — 不正遷移は ValueError
  - [ ] `list_by_status(filter)` — 一覧取得 (= 読み込み + filter)
  - [ ] fcntl ロックで同時書き込み防止
- [ ] `analyze/pipeline.py:_collect_novel_intent_candidates()` の戻り値を `IntentSuggestionRecord` 互換 dict に
- [ ] save phase で `suggestion_store.upsert()` を並行呼び出し (= 既存 single-file write を残したまま)
- [ ] テスト
  - [ ] `tests/test_suggestion_store.py` (= round-trip / dedupe / occurrences インクリメント / status 遷移 / 不正遷移拒否)
  - [ ] `tests/test_analyze_pipeline.py` に upsert 呼び出しの assertion 追加

### Phase 2: API (= 1 日)

- [ ] `routes/intent_suggestions.py` Blueprint
  - [ ] GET 一覧 (= filter + counts)
  - [ ] POST mark-reviewing / dismiss / accept
  - [ ] GET yaml snippet
- [ ] yaml snippet 生成ロジック (= `analyze/suggestion_yaml.py` に分離)
  - [ ] rationale を 1-2 行に圧縮 (= 既存 entry の description フォーマットに合わせる)
  - [ ] motion_intensity_bucket は rationale から heuristic 推定 (= 失敗時は `medium`)
  - [ ] 必須フィールドに `# TODO` を含めて出力
- [ ] merged 自動検出
  - [ ] GET 一覧時に `visual_intents.yaml` を読んで `accepted` 中の entry を `merged` に遅延更新
  - [ ] `part_registry_loader.load_registry("visual_intents")` を再利用 (= cache 経由)
- [ ] preview_server.py に Blueprint 登録
- [ ] テスト
  - [ ] `tests/test_routes_intent_suggestions.py` (= 各 endpoint の roundtrip / 不正遷移 409 / 存在しない id 404 / merged 遅延更新)

### Phase 3: UI (= 1-2 日)

- [ ] `frontend/src/pages/IntentCatalogPage.tsx`
  - [ ] `IntentSuggestionsSection` 追加 (= 最上段)
  - [ ] `useEffect` で `location.hash === "#suggestions"` を検知 → scrollIntoView
  - [ ] status フィルタ (clip_library と同じデザイン)
  - [ ] カード UI (= status badge / occurrences badge / 3 ボタン)
  - [ ] yaml snippet コピー UX (= clipboard API + inline preview + toast)
  - [ ] dismiss reason 入力モーダル
- [ ] `frontend/src/components/AnalyzeJobView.tsx` のリンク先に `#suggestions` を追加
- [ ] テスト
  - [ ] `IntentCatalogPage.test.tsx` (= 一覧 render / フィルタ / accept で snippet が clipboard に入る `vi.mocked(navigator.clipboard)`)
  - [ ] `AnalyzeJobView.test.tsx` の既存テストの hash 検証を追加

### Phase 4: マイグレーション + cleanup (= 0.5 日)

- [ ] `scripts/migrate_intent_suggestions.py`
  - [ ] `screenplays/*.suggested_intents.json` を全 scan
  - [ ] inbox に upsert (= 既存 status は保持)
  - [ ] 元ファイルを `data/intent_suggestions_archive/` に移動 (= `screenplays/` は git-tracked な template 領域なので runtime 退避は `data/` 配下に揃える)
  - [ ] `data/intent_suggestions.errors.log` に失敗 entry を記録
  - [ ] dry-run option (= `--dry-run`)
- [ ] preview_server.py 起動時 hook で 1 度だけ migration 実行
  - [ ] 二重実行防止: `data/intent_suggestions.json` が既に存在 + non-empty なら skip
- [ ] `analyze/pipeline.py` から個別 JSON 書き込みを削除 (= migration 完了後)
- [ ] テスト
  - [ ] `tests/test_migrate_intent_suggestions.py` (= 多 file / 既存 inbox との merge / 破損 file の扱い / dry-run)

### Phase 5: ドキュメント (= 0.5 日)

- [ ] `docs/plannings/2026-05-10_compositional-architecture.md` §8.2 に **本フローへのリンク + 廃止予定の旧経路を strikethrough**
- [ ] `docs/plannings/2026-05-10_clip-library-architecture.md` の IntentCatalog セクションに「💡 提案」記述を追加
- [ ] CLAUDE.md には記載しない (= 詳細すぎる)
- [ ] README に 1 段落: 「IntentCatalog 画面で novel intent をレビュー → snippet コピー → yaml に貼り付けて PR」

## 7. 不変条件 / アンチパターン

| 守るべき                             | 理由                                                                                     |
| ------------------------------------ | ---------------------------------------------------------------------------------------- |
| catalog yaml への自動書き込みは禁止  | 粒度の一貫性が崩れて cache hit 率が低下する                                              |
| `dismissed` の reason は必須         | 同候補が再提案された時に「前回なぜ却下したか」を見られないと判断ブレが起こる             |
| `accept` しても yaml 反映は別行為    | accept = 「採用予定」マークに過ぎない。yaml 編集 + PR は人間が行う                       |
| `_override_*` 経路は廃止しない       | 緊急 cold path として残す。本フロー導入後も常に動く                                      |
| `occurrences` は dedupe 後の累計のみ | suggestion を毎 analyze 実行で書き換えると履歴が消える                                   |
| `id` の算出に `description` を含める | 同 proposed_id でも description が違えば別 entry (= 異なる意味の候補を 1 つにまとめない) |

## 8. リスク + 対策

| リスク                                             | 対策                                                                                                                                                                                           |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 同時書き込みでファイル破損                         | `preview_server` は単一 process。`fcntl.LOCK_EX` で十分                                                                                                                                        |
| accept 後に PR が作られず放置                      | `merged` auto 検出で「N 日経っても merged にならない accepted」を UI で警告色 (= amber) 表示                                                                                                   |
| migration 中に analyze pipeline が回って整合性破壊 | startup の 1 回限りロック (= `data/intent_suggestions.json` 存在判定) + 既存 JSON は `data/intent_suggestions_archive/` へ退避                                                                 |
| 既存 JSON 読み込み失敗で全 inbox が空に            | migration は best-effort。失敗 entry は `data/intent_suggestions.errors.log` へ。inbox の作成は成功 entry だけで進める                                                                         |
| occurrences が無限増加                             | 候補が dismissed でも analyze pipeline は検出し続ける → status が `dismissed` の entry は upsert で `updated_at` と `occurrences` のみ更新、status は変えない (= 再浮上は UI からの明示操作で) |

## 9. 完了基準

- [ ] analyze 実行で suggestion が `data/intent_suggestions.json` に蓄積される
- [ ] IntentCatalog 画面 `/intent-catalog#suggestions` で proposed_id / description / scene_indices / rationale が表示される
- [ ] dismiss → reason 入力モーダル → DB 反映が動く (= 空 reason は拒否)
- [ ] accept → yaml snippet が clipboard にコピーされ、inline preview が表示される
- [ ] `visual_intents.yaml` に該当 id を追加 → 次の GET で status=merged になる
- [ ] AnalyzeJobView から `#suggestions` でジャンプし、対象セクションが viewport に入る
- [ ] migration script で既存 `*.suggested_intents.json` が吸い上げられ、archive に退避される
- [ ] 全 phase に対応するテストが pass

## 10. 参照 doc / コード

### 設計 doc

- `docs/plannings/2026-05-10_compositional-architecture.md` §8.2 (= novel intent 検出の元設計)
- `docs/plannings/2026-05-10_clip-library-architecture.md` §IntentCatalog (= 既存 UI 構造)
- `docs/plannings/2026-05-10_analyze-pipeline-conformance.md` §novel intent (= analyze 側既存実装の経緯)

### コード

- `analyze/intent_resolver.py:357 detect_novel_intent_candidates` (= 既存検出ロジック)
- `analyze/intent_resolver.py:88 NovelIntentCandidate` (= 既存 dataclass、本フロー導入後も中間形式として残す)
- `analyze/pipeline.py:514 _collect_novel_intent_candidates` (= save phase の現行 write 経路)
- `routes/clip_library.py` (= 同様の Blueprint パターン、本実装の参考)
- `frontend/src/pages/IntentCatalogPage.tsx` (= UI の追加先)
- `frontend/src/components/AnalyzeJobView.tsx:654-670` (= リンク改修先)

## 11. 補足: なぜ「半自動」で止めるか

「accept したら自動で yaml に追記 + PR 作成」までできる技術的余地はあるが、本設計では意図的に **snippet コピーで止める**。理由:

| 観点                    | 理由                                                                                                     |
| ----------------------- | -------------------------------------------------------------------------------------------------------- |
| 粒度判断                | description / suggested_kling_template / valid_start_emotions は意味的判断が必要。auto fill は雑音になる |
| 既存 entry との重複検査 | 似た意味の entry が既に yaml にあるかは人間が読まないと判断できない (= 自動 dedupe は誤判定リスク)       |
| PR レビュー文化との整合 | yaml 変更は必ず PR を経由する運用に揃える (= bot PR の auto-merge は別問題)                              |
| escape hatch 保護       | 自動 PR が暴走しても snippet コピー段階で止まれば被害ゼロ                                                |

= 「半自動」は **bug ではなく feature**。Phase 6 (= 任意の将来拡張) で「snippet を `gh pr create` まで運ぶ」ボタンを追加する余地は残すが、本フローでは入れない。
