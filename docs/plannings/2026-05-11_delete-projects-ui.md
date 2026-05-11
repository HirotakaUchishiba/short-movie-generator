# Delete Projects from UI — Design + Implementation Plan

**date**: 2026-05-11 / **status**: draft (= 実装 phase A 着手前) / **branch**: `feat/delete-projects-from-ui`

## 0. 背景

#193 で analyze 失敗時に UI が原因を表示できるようになったが、**失敗 project を一覧から削除する手段** は AnalyzeStage0Page (= `/project/<TS>/analyze` の中に潜る) からしか無い。プロジェクト一覧ページ (= `/`) からは削除できないため、screenshot のように失敗 project が貯まっていく:

```
既存プロジェクト
  [⚠ 分析失敗]
  (無題) 5/11 22:05
```

ユーザは:

1. 失敗 project の card をクリック
2. AnalyzeStage0Page に遷移
3. 削除ボタンを押す
4. confirm
5. TOP に戻る

を毎回繰り返す必要がある。**4 クリック × N 件** で UX が悪い。

本 doc では UI から既存 project を直接削除する機能を設計する:

- **per-card 削除**: 一覧の各 card 上にホバーで現れる 🗑 ボタン → 確認ダイアログ → 削除
- **一括削除**: 失敗 project N 件をまとめて削除する「失敗 N 件を削除」ボタン
- **削除内容の透明性**: confirm ダイアログに「何が削除される / 何が残るか」を明示

---

## 1. TL;DR

| 項目 | 内容 |
|---|---|
| **goal** | プロジェクト一覧から失敗 / 進行中 / 完了 全ての project を削除可能にする |
| **scope** | Frontend UI のみが主役。Backend は `DELETE /api/projects/<ts>` が既に十分なので追加 endpoint は 1 つ (`POST /api/projects/bulk-delete`) |
| **非 scope** | analytics DB の `analyze_jobs` / `posts` 行削除 (= 課金/投稿履歴として保持)。reference_video / `screenplays/auto_*.json` の削除 (= SHA dedup されてるので共有) |
| **Phase 数** | 3 (= Backend bulk endpoint / Frontend per-card delete / Frontend bulk delete) |
| **不変条件** | (1) 既存の AnalyzeStage0Page 削除導線は無変更、(2) 削除は確認ダイアログ必須、(3) in-flight analyze は cancel してから削除、(4) 共有資源 (reference_video / template) は触らない |
| **見積コスト** | 設計 0.5 日 + 実装 1 日 + テスト 0.5 日 |

---

## 2. 現状調査

### 2.1 Backend (= 既に存在)

| 項目 | 状況 | file:line |
|---|---|---|
| `DELETE /api/projects/<ts>` | ✅ 実装済 | `routes/projects.py:305-347` |
| 削除対象 | `temp/<TS>/` 全体 (shutil.rmtree) | `projects.py:339` |
| in-flight 検出 + cancel | 既実装 (`running` / `pending` / `dryrunning` / `awaiting_confirm`) | `projects.py:330-336` |
| `reference_videos/` 保持 | 意図的に残す (SHA dedup 共有) | docstring `projects.py:309-311` |
| `screenplays/auto_<sha>.json` 保持 | 意図的に残す (SHA dedup 共有) | (= 設計上、テンプレートは SHA-keyed) |
| `analytics.db.analyze_jobs` 保持 | 意図的に残す (課金 / 監査履歴) | (= 設計上) |
| `analytics.db.posts` 保持 | 意図的に残す (投稿実績) | (= 設計上) |
| 404 / 冪等性 | 404 を返す (= 既削除への DELETE は 失敗) | `projects.py:320-324` |
| frontend test | 5 件 (= dir 削除 / job cancel / video 保持 / 404 / 完了 job skip) | `tests/test_routes_projects_retry_delete.py:174-230` |

**結論**: backend は完成度が高い。bulk-delete endpoint を 1 つ足すだけで足りる。

### 2.2 Frontend (= 削除 UI 不足)

| 項目 | 状況 | file:line |
|---|---|---|
| `api.deleteProject(ts)` | ✅ 存在 | `frontend/src/api.ts` |
| AnalyzeStage0Page の削除 | ✅ 実装済 (`FailedActions` の StageFailureAlert → onDelete) | `frontend/src/pages/AnalyzeStage0Page.tsx:142-160` |
| ProjectList / ProjectCard の削除 UI | ❌ **無い** | `frontend/src/components/ProjectList.tsx` |
| 確認ダイアログの既存パターン | `window.confirm` (= ブラウザ native) | (= 共通 modal は無い) |
| 一括削除の UI / API | ❌ 無い | — |

**結論**: per-card 削除 + bulk delete を新規追加する。確認ダイアログは `window.confirm` で十分 (= 既存 pattern と一致)。

---

## 3. 設計方針

### 3.1 削除の意味論 (= 何を削除し、何を残すか)

```
削除する (= project-local):
  ✓ temp/<TS>/                           (screenplay / progress / tmp / metadata / final)
  ✓ in-flight analyze_job の cancel 要求 (= runner cancellation)

残す (= 共有資源 / 履歴):
  ✗ reference_videos/<sha>.<ext>         (= 他 project が同じ動画から作られる可能性)
  ✗ screenplays/auto_<sha>.json          (= 同じ参考動画なら同じ template が再利用される)
  ✗ analytics.db の analyze_jobs / phases (= 課金履歴・error 履歴を audit 用に保持)
  ✗ analytics.db の posts / post_metrics (= 過去の公開実績は意思決定に必要)
  ✗ data/cost_records.jsonl              (= 全 project 横断の cost 履歴)
  ✗ output/reels_<TS>.mp4                (= pipeline raw、Stage 6 が書き出し → Stage 7 が temp/<TS>/final に取込、raw は手動掃除)
```

`output/reels_<TS>.mp4` を残す理由: backend の現実装は `temp/<TS>/final/*` (= canonical 化済) は temp 削除で消えるが、`output/` 直下の pipeline raw は別パスなので消えない。Stage 7 取込済の動画はすでに `temp/<TS>/final/` に取り込まれている (= temp 削除で同時に消える) ので、`output/reels_<TS>.mp4` を残すのは「Stage 6 まで進んで Stage 7 取込前に削除した場合のみ」発生。これは **意図的に保持** (= raw は手動掃除、auto_loop の中間生成物は別運用)。

### 3.2 削除フローの 3 種類

#### (A) per-card 削除 (= 1 件削除、最頻出)

```
[card hover] → 🗑 button appears (top-right corner)
            → click → window.confirm("プロジェクト <TS> を削除しますか?\n
                                       削除: temp/<TS>/ ディレクトリ\n
                                       残す: 参考動画 / 分析履歴 / 投稿履歴")
            → DELETE /api/projects/<ts>
            → re-fetch list → card 消える
```

実装ポイント:

- 🗑 button は `e.preventDefault()` + `e.stopPropagation()` で card 全体の link 遷移を妨げる
- 失敗 project (= `analyze_status === "failed"`) は **常時表示** (= hover 不要)、card 全体のカラーも rose 系で目立たせる
- 削除中は busy state で disable + spinner

#### (B) bulk delete (= 失敗 N 件を一括削除)

```
一覧ヘッダに「⚠ 分析失敗 N 件をまとめて削除」button (= N=0 なら非表示)
  → click → window.confirm("失敗プロジェクト N 件を削除しますか?\n
                            (各 project の temp dir を削除、参考動画は保持)")
  → POST /api/projects/bulk-delete {ts_list: [...]}
  → re-fetch list → 失敗 card たちが消える
```

backend 新規 endpoint:

```python
POST /api/projects/bulk-delete
  body: {"ts_list": ["20260511_220521", "20260511_220522", ...]}
  response: {
    "deleted": ["20260511_220521"],
    "failed": [{"ts": "20260511_220522", "error_code": "PROJECT_NOT_FOUND", "message": "..."}],
  }
```

- 個別 ts を順次 `DELETE` 経路で削除し、エラーは収集して返す (= partial success 許容)
- 全部成功なら 200, 部分成功でも 200 (= status は body の `failed` 配列で判定)
- 全部失敗なら 200 (= UI が判定する; HTTP 500 にはしない、リトライ可能だから)

#### (C) 進行中 project の強制削除 (= 既存挙動の維持)

- backend は既に in-flight analyze_job を cancel してから削除する (`projects.py:328-336`)
- UI は confirm ダイアログに「分析実行中のジョブを中止して削除します」と追記すれば良い

### 3.3 確認ダイアログの文言 (= 一貫させる)

```
[per-card]
  プロジェクト「<title>」(<TS>) を削除しますか?

  削除:
    • temp/<TS>/ (= 台本 / 進捗 / 中間ファイル)
    • 分析実行中の場合はジョブを中止

  残す:
    • 参考動画 (他プロジェクトと共有)
    • 分析履歴 / 投稿履歴 (= analytics DB)

[bulk]
  分析失敗プロジェクト N 件を削除しますか?
  各プロジェクトの temp/<TS>/ ディレクトリを削除します。
  参考動画 / 履歴は保持されます。
```

`window.confirm` は文言の改行が制限されるが、UX 上「削除内容を明示する」ことが重要なので、native confirm に詰め込む。後で custom modal に upgrade する余地は残す。

### 3.4 UI コンポーネントの場所

```
frontend/src/components/
  ProjectList.tsx          ← bulk delete button をヘッダに、ProjectCard は次のとおり
  ProjectCard.tsx (split)  ← 既存は ProjectList.tsx 内に内包。削除 button 追加で大きくなるので別 file 検討
  common/
    DeleteProjectButton.tsx (新規)  ← 🗑 button + confirm + API 呼び出し + busy state
```

`DeleteProjectButton` を共通化することで AnalyzeStage0Page の `StageFailureAlert.onDelete` 経路と同じロジックを再利用可能 (= 確認文言・error handling の二重化を防ぐ)。

ただし AnalyzeStage0Page は既に `StageFailureAlert` 経由で削除しているので、無理に統一するより **削除関数だけ共通化** (= hook `useDeleteProject(ts)`) する方が変更幅が小さい。本 PR では:

- 共通 hook `useDeleteProject(ts)` を追加 (= confirm + API + navigate)
- `ProjectList.tsx` で per-card 削除ボタンに使う
- `AnalyzeStage0Page.tsx` の `FailedActions.onDelete` も同 hook 経由に統一

---

## 4. 実装計画 (= Phase 分割)

### Phase A: Backend bulk-delete endpoint

- [ ] **A1**: `routes/projects.py` に `POST /api/projects/bulk-delete` 追加。`ts_list` を受けて各 ts に対し既存 `api_delete_project` と同じロジックを順次実行、結果を `deleted` / `failed` 配列で返す
- [ ] **A2**: バリデーション (= `ts_list` が空 / 上限 100 件 / 各 ts の validate_ts)
- [ ] **A3**: `tests/test_routes_projects_bulk_delete.py` 新規 — 成功 / 部分失敗 / 全失敗 / 空 list / 上限超過 / in-flight cancel

**完了条件**: 新規 test pass + 既存 `test_routes_projects_retry_delete.py` も pass。

### Phase B: Frontend per-card 削除

- [ ] **B1**: `frontend/src/hooks/useDeleteProject.ts` 新規 — `{ deleteProject, busy, error }` を返す hook。`window.confirm` + `api.deleteProject` + callback で list refetch / navigation を呼び元に委譲
- [ ] **B2**: `frontend/src/components/common/DeleteProjectButton.tsx` 新規 — 🗑 button + `useDeleteProject` 連携。props で表示 mode (= compact icon / labeled button) を切替可能
- [ ] **B3**: `ProjectList.tsx` の `ProjectCard` に `DeleteProjectButton` を card 右上に配置。失敗 project は常時、それ以外は hover で表示。`e.preventDefault()` + `e.stopPropagation()` で link 遷移を抑制
- [ ] **B4**: `AnalyzeStage0Page.tsx` の `FailedActions.onDelete` も `useDeleteProject` 経由に統一 (= 重複ロジック解消)
- [ ] **B5**: `DeleteProjectButton.test.tsx` 新規 — 確認 cancel / API 成功 / API 失敗 / busy 中の disable

**完了条件**: vitest pass + tsc clean + `npm run build` 通る。

### Phase C: Frontend bulk delete

- [ ] **C1**: `frontend/src/api.ts` に `bulkDeleteProjects(tsList: string[]): Promise<{ deleted: string[]; failed: {...}[] }>` 追加
- [ ] **C2**: `ProjectList.tsx` 上部ヘッダに「⚠ 分析失敗 N 件を削除」button — N=0 なら非表示。click で confirm + bulkDeleteProjects + 再 fetch
- [ ] **C3**: 部分失敗時は失敗内容を inline error banner で表示 (= 既存の error 表示パターンを踏襲)
- [ ] **C4**: `tests/components/ProjectList.test.tsx` を拡張 (= bulk delete button の表示条件 / クリック挙動 / 失敗時のエラー表示)

**完了条件**: vitest pass + 失敗 project ばかりの一覧で bulk delete が正しく動く。

---

## 5. 影響範囲

### Backend (新規 1 / 改修 0)

- 新規: `routes/projects.py` に `bulk_delete` endpoint 追加 (= 既存 file への追記)
- 新規: `tests/test_routes_projects_bulk_delete.py`

### Frontend (新規 3 / 改修 4)

- 新規: `frontend/src/hooks/useDeleteProject.ts`
- 新規: `frontend/src/components/common/DeleteProjectButton.tsx` + `.test.tsx`
- 改修: `frontend/src/api.ts` (= `bulkDeleteProjects` 追加)
- 改修: `frontend/src/components/ProjectList.tsx` (= per-card button + bulk header button)
- 改修: `frontend/src/pages/AnalyzeStage0Page.tsx` (= `useDeleteProject` で統一)
- 改修: `frontend/src/components/ProjectList.test.tsx` (= bulk header 表示条件)

### Docs

- 本 doc (= `docs/plannings/2026-05-11_delete-projects-ui.md`)
- 完了後 `docs/developments/overview.md` §16 にエントリ追加

---

## 6. リスク / 不変条件チェック

| リスク | 緩和策 |
|---|---|
| 誤クリックで重要 project を削除 | `window.confirm` で title + TS を明示。card 右上の小さい button (= 大きく目立たせない) |
| 共有資源を誤って削除 (= reference_video / template) | backend は既に保護済 (`projects.py:309-311` の docstring 明示)。bulk-delete も既存 single-delete を順次呼ぶだけなので同じ保護を継承 |
| in-flight analyze の race | backend が cancel → rmtree の順序を保証 (`projects.py:328-339`)。bulk delete も同経路 |
| 100 件超の bulk-delete で server timeout | endpoint 側で `len(ts_list) > 100` を 400 で拒否 |
| frontend list の楽観更新による表示ズレ | 削除成功後に `reloadList()` で再 fetch (= 楽観更新しない) |

不変条件 verify:

- ✅ AnalyzeStage0Page の既存削除導線は維持 (= 内部実装を hook に統一するだけ)
- ✅ backend の single-delete 挙動 (= in-flight cancel / 共有資源保持) は無変更
- ✅ 確認ダイアログ必須 (= `window.confirm`)
- ✅ analytics DB / cost_records / reference_videos は触らない

---

## 7. テスト戦略

### Backend

1. **bulk_delete 成功** — 3 件 valid な ts で全 deleted
2. **bulk_delete 部分失敗** — 一部が存在しない ts、`failed` 配列に PROJECT_NOT_FOUND が入る
3. **bulk_delete 空 list** — 400 を返す
4. **bulk_delete 上限超過** — 101 件で 400
5. **bulk_delete + in-flight cancel** — running job の project を含む削除で cancel + rmtree が走る
6. **既存 single-delete の回帰** — `tests/test_routes_projects_retry_delete.py` の 5 件は変更後も全 pass

### Frontend

1. **useDeleteProject** — confirm cancel / API 成功 / API 失敗の callback 呼出
2. **DeleteProjectButton** — confirm OK で deleteProject 呼ばれる / cancel で呼ばれない / busy 中は disable
3. **ProjectList の per-card** — card 内の button click で link 遷移しない (= preventDefault)
4. **ProjectList の bulk header** — 失敗 0 件で非表示 / 1 件以上で N 件表示 / click で bulkDeleteProjects 呼ばれる
5. **AnalyzeStage0Page** — `useDeleteProject` 経由でも既存挙動を維持 (= navigate("/", { replace: true }))

---

## 8. 関連

- 元の screenshot 経路: 2026-05-11 22:09 JST に analyze 失敗で残った project `20260511_220521` が一覧に居座る
- 既存 backend: `routes/projects.py:305-347` (= DELETE 経路、十分な実装)
- 既存 frontend 削除導線: `pages/AnalyzeStage0Page.tsx:142-160` (= 唯一の delete 入口)
- 関連 PR: #193 (= pipeline failure UI 露出)
