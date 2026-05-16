# Stage 1 に背景・カメラ距離 per-scene editor を復活

> **作成日**: 2026-05-16
> **発端**: 「自動で登場人物・カメラ位置・背景を決定するが、人間の編集が入る余地はそれぞれ残すべき。UI は現在の台本編集 UI のままに、自動的に選択された値がアクティブ化された状態で編集ページを表示するべき」というユーザ要望。
> **前提**: PR #195 で「identity 系は完全自動、入力 UI 不要」として `LocationPicker` / `CameraDistancePicker` を撤去したが、本要望でその判断を見直す。

## WHY (= なぜやるか)

PR #195 では「identity 系は手動入力すべきでない、入力 UI も不要」という方針で per-scene の background / camera_distance picker を撤去した。その後 PR #196 で analyze が `location_ref` / `camera_distance` を自動選定するようになり、PR #197 で wardrobe-by-location rule が加わったことで、**「analyze が自動値を入れる + ユーザは Stage 1 で必要なら訂正できる」** という 2 段構えのほうがユーザ体験として自然になった。

現状:

- **登場人物**: editing UI (`FeaturedCharactersSection` / `SpeakerMappingSection` / `SceneCharacterSelector`) は残っている。analyze の自動値が pre-fill された状態で表示され、ユーザが訂正できる ✓
- **背景 (`location_ref`)** / **カメラ位置 (`camera_distance`)**: editing UI は撤去されており、ユーザが訂正する手段がない ✗

両者を **登場人物と同じ方式** (= 自動 pre-fill + 人間が訂正可能) に揃える。

## WHAT (= 修正の最終形)

### 1. per-scene `LocationPicker` を SceneEditor に復活

`ScriptEditPanel.tsx` 内に `LocationPicker` コンポーネントを再導入し、各 SceneEditor で `🎬 動き` (animation_style) と並べる。

- bind 先: `scene.location_ref` (abstract scene root、analyze が pre-fill)
- 選択肢: `api.listLocations()` で取得した全ロケ id (= `locations/<id>.json` の id 一覧)
- 空選択 (= `(未設定)`) も許容するが、診断バナーで警告される
- onChange は abstract scene の `location_ref` を更新 (= local state、保存時に PUT `/api/projects/<ts>/abstract`)

### 2. per-scene `CameraDistancePicker` を SceneEditor に復活

同じく `CameraDistancePicker` を再導入。

- bind 先: `scene.camera_distance`
- 選択肢: `close-up` / `medium-close` / `medium` / `wide` の 4 enum
- 空選択は許容 (= `_derive_identity` の fallback でロケ既定 → `medium-close` に展開)

### 3. diagnostics 復活

PR #195 で削除した `AbstractDiagnostics` の 2 フィールドを復活させる:

- `scenes_without_location: number[]` — `location_ref` が空のシーン idx
- `invalid_camera_distance: { scene_idx, value }[]` — enum 外の `camera_distance` (= 通常は発生しないが念のため)

`computeDiagnostics` で算出し、`CompletenessBanner` に「背景未設定シーン」「不正カメラ距離」を表示する。

### 4. 「✨ analyze 推定」表示

既存の `hasAnalyzeSpeakerProfiles(abstract)` 関数を再利用し、analyze が走ったプロジェクトの SceneEditor 内 picker 列にバッジを 1 つ表示する (= 「これらは analyze の自動値です。必要なら訂正してください」のヒント)。シーンごとではなく各シーンの picker セクションの先頭に 1 つで十分。

## scope 外 (= 本機能で踏み込まないこと)

- **bulk apply の location/camera 復活**: PR #195 で `animation_style` のみに縮小済み。analyze が per-scene で適切な値を入れているので bulk apply の必要性は下がっている。現状維持
- **identity / annotation の編集 UI 再導入**: PR #195 で撤去した IdentityEditor / AnnotationEditor は復活させない (= identity は derived、annotation は best-effort で人間が編集する意義が薄い)
- **backend / analyze 側の変更**: 一切なし。本 PR は frontend のみ

## HOW (= phase 分解)

全 3 phase、本セッション内で順次実装する (= worktree `feat/restore-scene-pickers` 上)。

### Phase 1: LocationPicker + CameraDistancePicker 復活

| 対象                                                 | 内容                                                                                                                                                                                                                           |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `frontend/src/components/stages/ScriptEditPanel.tsx` | `LocationPicker` / `CameraDistancePicker` を内部定義として復活。`ScriptEditPanel` で `api.listLocations()` を fetch、`locationIds` state を `SceneEditor` に渡す。`SceneEditor` で animation_style picker と並べてレンダリング |

### Phase 2: diagnostics + 「✨ analyze 推定」表示

| 対象                                                 | 内容                                                                                                                                                                    |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/types.ts`                              | `AbstractDiagnostics` に `scenes_without_location: number[]` と `invalid_camera_distance: { scene_idx, value }[]` を復活                                                |
| `frontend/src/components/stages/ScriptEditPanel.tsx` | `computeDiagnostics` で 2 フィールドを算出。`CompletenessBanner` の表示分岐を復活。各 SceneEditor の picker セクション先頭に `<AnalyzeSuggestedBadge />` を条件付き表示 |

### Phase 3: テスト + docs

| 対象                                                      | 内容                                                                  |
| --------------------------------------------------------- | --------------------------------------------------------------------- |
| `frontend/src/components/stages/ScriptEditPanel.test.tsx` | diagnostics 計算 (空 location_ref / enum 外 camera_distance) のテスト |
| `docs/abstract-screenplay-design.md` §9                   | Stage 1 UI に背景/カメラ距離 picker が復活した旨を反映                |

## 不変条件 (= 守るべきルール)

1. **analyze の自動値は触らない**: backend / analyze は無変更。フロントエンドが既存の `scene.location_ref` / `scene.camera_distance` を表示・編集するだけ
2. **identity / annotation editor は復活させない**: PR #195 の判断 (= identity は derived、annotation は best-effort) を維持
3. **既存の登場人物編集 UI は無変更**: PR #196 で導入した FeaturedCharactersSection / SpeakerMappingSection / SceneCharacterSelector はそのまま

## 検証手順

### Phase 単位

各 phase は実装と同時にテストを書き、該当 test を pass させる。

### 統合検証 (= 全 phase 完了後)

1. **frontend build** — `npm run build` が tsc + vite で成功
2. **frontend test** — `npm run test:ci` が全 pass
3. **backend full test** — `pytest tests/` が 0 failed (= 本 PR は frontend のみだが、念のため)
4. **機能確認**: analyze 経由のプロジェクトを開き、各シーンの背景・カメラ距離 picker に analyze の値が pre-fill されていること、空にすると completeness banner で警告されることを確認 (= 手動)

## 関連ドキュメント

- `docs/plannings/2026-05-12_legacy-schema-removal.md` — PR #195 で picker を撤去した経緯
- `docs/plannings/2026-05-15_auto-casting-detection.md` — PR #196 で casting 自動提案を導入
- `docs/plannings/2026-05-16_wardrobe-by-location.md` — PR #197 で wardrobe rule を追加
