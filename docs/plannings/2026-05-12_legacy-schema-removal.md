# 抽象台本 identity / annotation 完全自動化 + 旧スキーマ撤去

> **作成日**: 2026-05-12
> **発端**: Stage 1 編集 UI の identity / annotation 入力欄を確認したところ、これらは analyze pipeline の責務であり、手動入力されるべきものではないことが判明。旧スキーマ (= flat field) からの fallback も負債として撤去する。

## WHY (= なぜやるか)

### 現状の問題

1. **identity が "不完全" になる scene が発生する**
   - `analyze/compose.py:_derive_identity` は character_refs / location_ref / start_emotion のいずれかが欠落すると `None` を返す
   - その結果 `scene["identity"]` が書き込まれず、UI で「不完全」表示になり、ユーザに手動補完を要求する
   - これは「**analyze が SSOT、手動入力経路は廃止**」という設計方針に反する

2. **flat schema fallback が負債化している**
   - `clip_library.py:_scene_to_identity` は `scene["identity"]` が無ければ flat `scene.character_refs` 等を読む fallback パスを持つ
   - `scene_has_identity` も nested / flat の両 schema を受け入れる
   - `screenplay_validator.py` も JSON schema 上で両 schema を valid 扱い
   - `bg_cache.py` / `kling_cache.py` / `scene_gen.py` / `composition_id.py` は flat field のみを読んでおり、nested schema に追従していない
   - 2 schema が並走することで、どちらを書くか / どちらを読むかが file ごとにバラつき、不整合の温床になる

3. **編集 UI が手動入力を誘発している**
   - Stage 1 の `IdentityEditor` / `AnnotationEditor` は「analyze が埋めるべき」field を user に編集させる UI
   - Stage 3/4 の `SceneFieldEditor` は location_ref / camera_distance を inline 編集できる UI
   - これらの存在自体が「identity は手動でも入れられる」という誤った前提を与える

### 解決後の状態

- `scene.identity` / `scene.annotation` は analyze pipeline が SSOT として常に produce する (= 失敗時は fail-fast、defaults なし)
- flat schema は完全撤去 (= compose は nested のみ書き、全 readers は nested のみ読む)
- identity / annotation の編集 UI は存在しない (= user は再 analyze するか screenplay JSON を直接編集する以外に変更経路を持たない)

---

## WHAT (= 修正の最終形)

### 1. compose の identity 派生は fail-fast

`analyze/compose.py:_derive_identity` を「**必須 field が無ければ `ValueError` を投げる**」実装に変更。`None` 返却を廃止。

| field           | 現状の挙動                                | 修正後の挙動                    |
| --------------- | ----------------------------------------- | ------------------------------- |
| character_refs  | 空なら `None`                             | **空は許容** (= 背景のみシーン) |
| location_ref    | 空なら `None`                             | 空なら `ValueError`             |
| start_emotion   | 全 line に emotion 無しなら `None`        | 同上 `ValueError`               |
| camera_distance | location 既定 → `"medium-close"` fallback | 既存挙動維持                    |

`location_ref` / `start_emotion` が欠落するのは analyze pipeline のバグ (= Claude が必須出力を omit した、frame 入力が空、等) なので、無理に default を入れずに analyze を fail させて user に再実行を促す。

### 2. video_analyzer の annotation は常時 populate

`video_analyzer.py` の annotation 後処理を変更。`confidence < 0.7` での `None` drop を廃止し、Claude が返した値をそのまま採用する。Claude が annotation を omit したら、その 1 scene のみ annotation 欠落 (= soft rank が効かないだけで identity 検索は動く) という degrade に留める。

### 3. flat schema を完全撤去 (= nested only)

下記の readers / writers から flat schema へのアクセスを全て削除:

**Writers**:

- `analyze/compose.py:233-300` — `scene["character_refs"]`, `scene["location_ref"]`, `scene["camera_distance"]` の flat write を削除。`scene["identity"]` / `scene["annotation"]` のみ書く。`scene["characters"]` (= UI 表示用 metadata) は残す。

**Readers**:

- `clip_library.py:_scene_to_identity` — flat fallback 削除
- `clip_library.py:_scene_to_annotation_request` — flat fallback 削除
- `clip_library.py:scene_has_identity` — flat fallback 削除
- `screenplay_validator.py` — JSON schema から flat alternative を削除、全 reader を nested 経由に
- `bg_cache.py` — `scene["identity"]["character_refs"]` / `["location_ref"]` 経由
- `kling_cache.py` — `scene["identity"]["camera_distance"]` / `["location_ref"]` 経由
- `scene_gen.py` — `scene["identity"]["character_refs"]` / `["location_ref"]` / `["camera_distance"]` 経由
- `composition_id.py` — dataclass populator を nested 起点に

### 4. 編集 UI を全削除

| 削除対象                                                  | 場所                              | 影響                                                                                  |
| --------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------- |
| `IdentityEditor.tsx` + test                               | `frontend/src/components/`        | Stage 1 から削除                                                                      |
| `AnnotationEditor.tsx` + test                             | `frontend/src/components/`        | Stage 1 から削除                                                                      |
| `SceneFieldEditor.tsx` + test                             | `frontend/src/components/`        | Stage 3 / 4 から削除                                                                  |
| `ScriptEditPanel.tsx` の host 部分                        | `frontend/src/components/`        | identity / annotation セクション撤去                                                  |
| `StageBG.tsx` / `StageKling.tsx` の SceneFieldEditor 呼出 | `frontend/src/components/stages/` | inline 編集無くなる、再生成ボタンのみ残る                                             |
| `types.ts` の flat field                                  | `frontend/src/`                   | `Scene` / `AbstractScene` から flat field 削除、`identity` / `annotation` は required |
| `api.ts` の `patchScene`                                  | `frontend/src/`                   | call site が無くなったら削除                                                          |

### 5. PATCH endpoint 撤去

`preview_server.py` の `PATCH /api/projects/<ts>/scenes/<int:scene_idx>` を完全撤去。call site (= SceneFieldEditor) が無くなるため。同 endpoint 経由で screenplay snapshot を mutate する経路を閉じる。

---

## HOW (= phase 分解と worktree branch 戦略)

**全 7 phase**、各 phase を独立した worktree + branch で並列開発。merge は依存順。

### Phase × Worktree Branch マトリクス

| #      | branch 名                                 | 対象 file                                                                                                                                                                   | 依存                                   |
| ------ | ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| **W1** | `refactor/identity-1-derive-fail-fast`    | `analyze/compose.py:_derive_identity` (lines 305-362) + `tests/test_analyze_compose.py`                                                                                     | —                                      |
| **W2** | `refactor/identity-2-clip-library-nested` | `clip_library.py` の `_scene_to_identity` / `_scene_to_annotation_request` / `scene_has_identity` + `tests/test_clip_library*.py`                                           | —                                      |
| **W3** | `refactor/identity-3-validator-nested`    | `screenplay_validator.py` + 関連 test                                                                                                                                       | —                                      |
| **W4** | `refactor/identity-4-annotation-always`   | `video_analyzer.py` の annotation 後処理 + `tests/test_video_analyzer.py`                                                                                                   | —                                      |
| **W5** | `refactor/identity-5-downstream-nested`   | `bg_cache.py` / `kling_cache.py` / `scene_gen.py` / `composition_id.py` + `analyze/compose.py:233-300` (= flat write 削除) + 関連 test                                      | **W1, W2** merge 後                    |
| **W6** | `refactor/identity-6-ui-removal`          | `IdentityEditor.tsx` / `AnnotationEditor.tsx` / `SceneFieldEditor.tsx` + tests + `ScriptEditPanel.tsx` / `StageBG.tsx` / `StageKling.tsx` の host 部分 + `types.ts` cleanup | —                                      |
| **W7** | `refactor/identity-7-patch-cleanup`       | `preview_server.py` の PATCH endpoint 撤去 + `api.ts` の `patchScene` 削除                                                                                                  | **W6** merge 後 (= call site 無くなる) |

### 並列実行戦略

```
時系列 →
[Wave 1: 全 7 branch 同時着手 (= worktree で並列)]
  W1 ──┐
  W2 ──┤
  W3 ──┤
  W4 ──┤
  W5 ──┤ (= 開発は並列。merge 順は依存に従う)
  W6 ──┤
  W7 ──┘

[Wave 2: merge は依存順]
  Step 1: W1, W2, W3, W4, W6 → main (任意順)
  Step 2: W5 → main (= W1, W2 が merge 済みであることを確認)
  Step 3: W7 → main (= W6 が merge 済み)
```

### 各 phase の worktree 担当 subagent prompt 概要

各 worktree は独立した subagent (= Agent tool with `isolation: "worktree"`) で実行。

- 入力: 本ドキュメントの該当 phase 節 + scope file 一覧 + 修正後の挙動仕様
- 出力: branch 名 + 修正コミット + test pass の報告
- 不変条件: scope 外の file を絶対に編集しない

---

## 不変条件 (= 守るべきルール)

1. **抽象台本は analyze が SSOT**。compose 以降の経路では identity / annotation を mutate しない (= UI / API patch も含めて全撤去)
2. **flat schema は禁止**。`scene["character_refs"]` / `scene["location_ref"]` / `scene["camera_distance"]` を scene root に書く・読む経路は禁止 (= test で grep 検知すべき)
3. **identity の必須 field は 3 つ** (character_refs を許容範囲とした上で location_ref + start_emotion + camera_distance)。camera_distance のみ default 許容、他は fail-fast
4. **annotation は best-effort**。Claude が空でも analyze を fail させない (= soft rank が効かないだけで pipeline は進む)

---

## 検証手順

### Phase 単位

- 各 worktree は独立した unit test を pass させること
- 該当範囲外の test (= 他 phase の責務) は無視して良い

### 統合検証 (= 全 phase merge 後)

1. **analyze pipeline E2E**: `python3 scripts/analyze_video.py drafts/<sample>.mov` で screenplay JSON が生成され、全 scene に `identity` + `annotation` (= optional fields は含まれる場合のみ) が書き込まれていることを確認
2. **compose 出力 verification**: 生成された `screenplay.json` を grep し、scene root に flat field (`character_refs` / `location_ref` 等) が **無い** ことを確認
3. **Stage 3 + 4 cache**: 既存 `screenplays/auto_*.json` で `python3 main.py <name>` を起動し、Stage 3 (背景生成) / Stage 4 (Kling) が nested identity を読んで正常動作することを確認
4. **clip_library**: `CLIP_LIBRARY_ENABLED=1` で再実行し、warm path (= 過去 entry の再利用) が hit することを確認
5. **UI 動作**: フロント dev server (`npm run dev`) を起動し、Stage 1 ページから identity / annotation 編集セクションが消えていること、Stage 3 / 4 から inline 編集 UI が消えていること、再生成ボタンのみ残っていることをブラウザで確認

### 既存データへの影響

既存の `screenplays/auto_*.json` (= 旧 analyze 出力) は flat field を持つが、本修正後の compose は read しない (= nested のみ)。よって **analyze の再実行が必要**。既存 project (= `temp/<TS>/screenplay.json` snapshot) は影響を受ける可能性があり、Stage 6 までしか完了していない project は再 analyze 推奨。

---

## 影響範囲外 (= 本修正で触らない)

- Stage 2 (TTS) — `voice_overrides` / `audio_tags` 関連は範囲外
- Stage 6 (overlay) — subtitle / 字幕周りは別系統
- analytics DB schema — `screenplays` table の hook_type / tone / dominant_emotion 等のタグは別経路
- character_selection / animation_style — これらは identity field ではない (= compose 入力の hint) ので、書き込み経路は残す (= ただし PATCH 経由で mutate する経路は撤去)

---

## 関連ドキュメント

- `docs/abstract-screenplay-design.md` — identity / annotation の設計詳細 (= 本修正で更新が必要な箇所あり)
- `docs/plannings/2026-05-10_compositional-architecture.md` — Layer 1 (clip_library) の identity 利用
- `docs/plannings/2026-05-10_architecture-mismatch-audit.md` — Layer 1 の wire 状況
