# analyze → project 一本化 設計ドキュメント

| 項目       | 値                                                                                                                                                                        |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 作成       | 2026-05-10                                                                                                                                                                |
| ステータス | proposal (= 実装着手前)                                                                                                                                                   |
| 関連       | `docs/abstract-screenplay-design.md`, `frontend/src/components/AnalyzeJobView.tsx`, `frontend/src/components/ProjectList.tsx`, `routes/projects.py`, `staged_pipeline.py` |
| スコープ   | UX フロー + backend エンドポイント + state machine。analyze pipeline 自体のロジック・抽象台本スキーマは触らない                                                           |

---

## 1. 問題定義

### 1.1 現状フロー (= 非効率)

```
[A] 参考動画を analyze pipeline に投げる (= TOP の analyze 起動 UI)
        ↓
[B] AnalyzeJobView がコスト確認 → analyze 進捗 SSE → save phase 完了
        ↓
[C] 完了モーダルに「プロジェクト作成」ボタンが表示される
        ↓
[D] ユーザーがボタンを押す
        ↓
[E] POST /api/projects { screenplay_name, analyze_job_id } → /project/<TS>/script へリダイレクト
```

[C][D] が **手動操作** で、ここが UX の摩擦点になっている:

- 「プロジェクト作成」ボタンが完了モーダル内の他の情報と同じ階層に並んでいて視認性が低い
- 進捗を見ていたユーザーが完了通知でモーダルを閉じてしまうと、TOP に戻ってドロップダウンから `auto_<sha>.json` を選び直す回り道に陥る
- 心理モデル上「analyze は 1 つの完結したジョブ、project はその後で別途作る」という分断が生まれ、`POST /api/projects` を毎回意識的に呼ぶ運用になっている

### 1.2 問題の本質

「参考動画を analyze する」という行為と「その動画から動画を生成する project を作る」という行為は、運用上は **常に連続** している (= 単独で analyze だけしたいケースは template 量産用途のみ)。にもかかわらず UI / API の境界が「analyze ジョブ完結」と「project 作成」に分かれているため、ユーザーは同じ意思決定を 2 回連続で要求される。

冗長な確認は判断疲れと操作ミス (= 完了モーダル誤閉じ → TOP 経由) を引き起こす。

---

## 2. 設計方針

### 2.1 主張

**analyze pipeline を「project の Stage 0」相当の internal フェーズとして位置付ける。** TOP からの主動作を「project 作成」にして、参考動画の analyze は project 生成プロセスの一部として走る。

### 2.2 ユースケース別の経路

| #   | ユースケース                                       | 経路                                                                                              |
| --- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 1   | 参考動画から新規 project を作る (= **主導フロー**) | TOP「📹 参考動画から作成」→ project 作成 + analyze 起動 → Stage 0 進捗ページ → Stage 1 へ自動遷移 |
| 2   | 既存 `auto_<sha>.json` template から project       | TOP「既存 template から作成」(= 現行ドロップダウン) → POST /api/projects → Stage 1                |
| 3   | 同じ参考動画から 2 つ目以降の project を量産       | analyze 結果は `screenplays/auto_<sha>.json` に残るので #2 経路で 0 コスト project 化             |
| 4   | analyze だけ走らせて template を作りたい           | #1 経路で project を作り、Stage 0 完了後に project を削除すれば template だけ残る                 |

主動作 (= #1) を新設、#2 〜 #4 は既存資産で吸収する。

### 2.3 Stage 0 の位置付け

既存の段階的ゲート方式に Stage 0 を追加:

```
[0. analyze] → [1. script] → [2. tts] → [3. bg] → [4. kling] → [5. scene] → [6. overlay (= raw)] → [7. final import] → [8. publish]
```

- `metadata.analyze_job_id` が non-null かつ analyze ジョブが running 中 → state = Stage 0
- save phase 完了 → Stage 0 done → Stage 1 が unlock
- analyze 失敗時の project は「Stage 0 failed」状態で残す (= retry / 削除を UI で選択可能)

template 経由作成 (= 既存 `POST /api/projects`) は Stage 0 を skip して直接 Stage 1 から始まる。

---

## 3. アーキテクチャ詳細

### 3.1 新エンドポイント

#### `POST /api/projects/from-reference-video`

project + analyze ジョブを 1 トランザクションで作成する。

```http
POST /api/projects/from-reference-video
Content-Type: multipart/form-data

reference_video=<binary>
instructions=<optional string>
fps=<optional float, default 2.0>
```

レスポンス:

```json
{
  "ts": "20260510_150000",
  "analyze_job_id": "abc123"
}
```

副作用:

1. `temp/<TS>/` ディレクトリ作成、`metadata.json` を `analyze_job_id` 埋めで初期化 (= `screenplay_name` は `null` または `"pending"`)
2. analyze pipeline ジョブを enqueue (= 既存 `analyze_jobs` ストア + worker を再利用)
3. analyze save phase 完了時に backend が:
   - 既存通り `screenplays/auto_<sha>.json` を生成
   - `metadata.json.screenplay_name` を `auto_<sha>.json` に更新
   - `temp/<TS>/screenplay.json` snapshot を `load_template` 経由でコピー
   - Stage 1 を unlock

### 3.2 既存エンドポイントの位置付け

| Endpoint                                                  | 残す                 | 用途                                                                                 |
| --------------------------------------------------------- | -------------------- | ------------------------------------------------------------------------------------ |
| `POST /api/analyze-jobs`                                  | ✅ 残す (= 内部利用) | analyze 単独起動 (= 新エンドポイントが内部で再利用)。external trigger は段階廃止予定 |
| `POST /api/projects` (= screenplay_name + analyze_job_id) | ✅ 残す              | template 経由 project 化 (= 量産経路 #2 / #3)                                        |

### 3.3 SSE event の継承

analyze ジョブの SSE event (= `phase_start` / `phase_complete` / `dryrun_complete` / `awaiting_confirm` / `completed` / `failed`) はそのまま使う。フロントは購読位置だけ変える:

| 経路            | 購読側                                   | `completed` 時の動作                |
| --------------- | ---------------------------------------- | ----------------------------------- |
| 主導フロー (#1) | Stage 0 page (= `/project/<TS>/analyze`) | `/project/<TS>/script` に自動遷移   |
| 既存フロー (旧) | standalone AnalyzeJobView                | 「プロジェクト作成」ボタンを enable |

旧フローは Phase E で完全削除する (= §6 参照)。

---

## 4. UI 変更

### 4.1 TOP page (= `ProjectList`)

| 領域       | Before                                                 | After                                                                                         |
| ---------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| **主動作** | screenplay ドロップダウン + 「プロジェクト作成」ボタン | 「📹 参考動画から作成」(= primary CTA、ファイル選択 + instructions textarea + 「作成」ボタン) |
| **副動作** | (= analyze は別ページ)                                 | 折りたたみセクション「既存 template から作成」内に現行 UI を移動 (= 量産・再利用ユーザー向け) |
| **既存**   | 既存プロジェクト一覧                                   | 変更なし                                                                                      |

### 4.2 Stage 0 page (新規)

- パス: `/project/<TS>/analyze`
- 既存 `AnalyzeJobView` コンポーネントを再利用、props で「project-internal モード」フラグを渡す
- save 完了 (= `phase_complete: save`) で `/project/<TS>/script` に自動遷移 (= ボタン待ち無し)
- `awaiting_confirm` (= cost confirmation) の UI は同じ。「取り消し」を押した場合は project ごと削除するか確認 dialog を出す
- 失敗時は「retry」「削除」「TOP に戻る」の 3 択を提示

### 4.3 既存 standalone AnalyzeJobView

- Phase D で「Stage 0 経路に移行中」notice を上部に表示
- Phase E で完全削除

### 4.4 Stage 1「素材編集」パネル

変更なし。`metadata.analyze_job_id` が non-null なら表示する条件は同じ。

---

## 5. データモデル変更

### 5.1 `metadata.json`

```json
{
  "ts": "20260510_150000",
  "screenplay_name": null, // Stage 0 中は null、save 完了で auto_<sha>.json
  "screenplay_sha256": null,
  "analyze_job_id": "abc123",
  "stage_progress": {
    "analyze": { "status": "running" } // 新キー
  }
}
```

`screenplay_name` を nullable に拡張するため、既存コードで前提になっている箇所 (= ingest_video, dashboard, validator 等) を Phase A の grep 監査で defensive 化する。

### 5.2 `progress_store`

新しい stage key `analyze` を追加:

| state       | 説明                                     |
| ----------- | ---------------------------------------- |
| `running`   | analyze ジョブが in-flight               |
| `completed` | save phase 完了 → Stage 1 unlock         |
| `failed`    | analyze 失敗 → retry / 削除 を UI で選択 |

approve / revoke 操作は不要 (= 完了 / 失敗の単発 transition のみ)。

---

## 6. 段階的実装プラン

| Phase | 内容                                                                                                         | 期間目安 | 独立 PR |
| ----- | ------------------------------------------------------------------------------------------------------------ | -------- | ------- |
| **A** | backend: `POST /api/projects/from-reference-video` 実装、metadata.screenplay_name=null 状態への defensive 化 | 1〜2 日  | ✅      |
| **B** | frontend: `/project/<TS>/analyze` route 追加、AnalyzeJobView の project-internal モード、自動遷移実装        | 1 日     | ✅      |
| **C** | TOP 改修: 「📹 参考動画から作成」CTA 追加、既存 UI を「既存 template から作成」セクションに移動              | 0.5 日   | ✅      |
| **D** | 旧 standalone AnalyzeJobView page に「Stage 0 経路に移行中」notice 追加                                      | 0.5 日   | ✅      |
| **E** | 旧経路を完全削除 (= 運用 1 週間後)                                                                           | 0.5 日   | ✅      |

各 phase は独立 PR として並行に進められる構造にする (= A/B/C/D は base が同じ、E のみ A〜D 後)。

---

## 7. リスクと未解決事項

### 7.1 analyze 失敗時の project の扱い

- 候補 1: 失敗 → project を自動削除 (= 残骸が出ない)
- 候補 2: 「Stage 0 failed」状態で残し、retry と削除を UI で選択可能に
- **推奨: 候補 2**。analyze の中間 cache (= frames / audio / whisper) は content-addressed で再利用可能なので、retry は無料に近い。残しておくほうが復旧しやすい

### 7.2 analyze 中の他の操作

- Stage 0 が走っている間、その project 自身の Stage 1 以降は disable
- ただし「analyze をキャンセルして TOP に戻る」「並行で他の project の Stage 1 を進める」は許可
- preview_server の `job_store` は既に複数 job 並行 OK

### 7.3 analyze 結果を「template だけ」に残したいケース

- ユースケース #4 は標準フローの副作用 (= analyze save phase は必ず `screenplays/auto_<sha>.json` を write) で吸収できる
- Stage 0 完了後に project を削除すれば template だけ残る
- 専用エントリーポイント (= TOP に「template だけ作成」ボタン) は不要

### 7.4 同じ参考動画で 2 回目以降の project 作成

- 1 回目: 主導フロー (#1) で analyze + project
- 2 回目: TOP の「既存 template」経路 (#2 / #3) で `auto_<sha>.json` を選ぶ
- analyze 自体は content-addressed cache で 2 回目を skip するので、たとえ #1 経路で同じ動画を 2 回投げても analyze コストは 0 (= 既存挙動)

### 7.5 `metadata.screenplay_name` が pending な project の影響範囲

Phase A の最初に grep で全箇所監査:

- `staged_pipeline.write_metadata` / `load_template` / `load_project_screenplay`
- `routes/projects.py` の各 endpoint
- `scripts/ingest_video.py` / `scripts/ingest_screenplay.py` / `scripts/dashboard.py`
- `screenplay_validator.py`

`null` または `"pending"` を許容する分岐を追加するか、別フィールド (= `analyze_status`) で「pending」を表現するかを Phase A で決める。

### 7.6 Stage 0 中の project が UI 一覧でどう見えるか

- TOP の「既存プロジェクト」一覧に Stage 0 中の project が出る → state バッジで「📹 analyze 中」を表示
- クリックで Stage 0 page に飛ぶ
- 一覧 sort は `created_at` 降順そのまま

---

## 8. スコープ外

- analyze pipeline 自体のロジック変更 (= frames / audio / whisper / claude phase の改修)
- Stage 1「素材編集」UI の機能追加 (= location_ref 推論、bulk apply の改善 etc.)
- 抽象台本スキーマの変更 (= `docs/abstract-screenplay-design.md` に従う)
- 「複数の参考動画を 1 project にまとめる」「複数 project を 1 video に統合する」(= 別議論)
- analyze pipeline のコスト試算ロジックの変更 (= 既存 `data/cost_records.jsonl` median を使う)

---

## 9. 受け入れ基準 (= Phase E 完了時点)

1. TOP に「📹 参考動画から作成」CTA が表示され、ファイル選択 → 「作成」だけで project + analyze が起動する
2. analyze 進捗 page (= Stage 0) で `awaiting_confirm` のコスト確認以外、ユーザー操作は不要 (= 完了で自動的に Stage 1 page へ)
3. 旧 standalone AnalyzeJobView page が削除されている
4. `POST /api/projects` (= 既存 template 経由) は 「既存 template から作成」セクションから到達でき、後方互換が保たれている
5. analyze 失敗時に「retry」「削除」「TOP に戻る」のいずれかを選べる
6. 既存の analyze cache (= content-addressed frames / audio) が壊れていない (= 再 analyze が無料に近いまま)

---

## 10. 関連ドキュメント / コード

- `docs/abstract-screenplay-design.md` §1 全体像 — 現状の analyze → create-project の 2 段モデル
- `frontend/src/components/AnalyzeJobView.tsx` — analyze 進捗 UI (= 完了時のボタン: line 671-696)
- `frontend/src/components/ProjectList.tsx` — TOP の project 作成 UI (= ドロップダウン: line 186-208)
- `frontend/src/api.ts` — `createProject(screenplayName, jobId)` (= line 120-129)
- `routes/projects.py` — `POST /api/projects` ハンドラ (= line 83-131, `_list_screenplays` line 33-38)
- `staged_pipeline.py` — `write_metadata` (= line 208-234)
