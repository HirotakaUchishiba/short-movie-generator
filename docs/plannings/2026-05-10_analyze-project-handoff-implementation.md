# analyze → project 一本化 実装方針ドキュメント

| 項目         | 値                                                                     |
| ------------ | ---------------------------------------------------------------------- |
| 作成         | 2026-05-10                                                             |
| ベース設計   | `docs/plannings/2026-05-10_analyze-project-handoff.md`                 |
| ステータス   | completed (= 全 Phase merged: #173 / #178 / #179 / #180 / #181 / #182) |
| 対象ブランチ | `feat/analyze-project-handoff-unification` (= worktree、上流: `main`)  |

---

## 0. このドキュメントの目的

ベース設計 (= why / what) は確定済み。本ドキュメントは「**各 Phase で具体的にどのファイル / 関数 / 行を、どう変更するか**」を関数単位 / 行単位で詰めた **実装方針** を提供する。

設計上の主張は変更しない (= analyze は project の Stage 0 として位置付ける)。

---

## A. 影響範囲監査: `metadata.screenplay_name` を nullable にする

### A.1 監査結果一覧

下記は `metadata.json.screenplay_name` が `None` または `"pending"` 状態のときに**現状壊れる箇所** + **修正方針** を網羅する。grep ベース (= `grep -n "screenplay_name" *.py routes/*.py scripts/*.py`)。

| ファイル:行                                       | 関数                                                               | 現状の前提                                                                                                                         | null 時の挙動                                                                                | 修正方針                                                                                                                                                                                                                       |
| ------------------------------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------- | ----------- | ----------------------------------- | ------------ |
| `staged_pipeline.py:208-235`                      | `write_metadata(temp_dir, screenplay_name: str, ...)`              | `screenplay_name: str` 必須、`screenplay_template_name` も同値で書く                                                               | str を期待しているが `None` を渡せば dict に `None` が書かれて downstream で fallback が利く | \*\*シグネチャを `screenplay_name: str                                                                                                                                                                                         | None = None` に変更**。`None`の場合は`screenplay_name`/`screenplay_template_name` を omit (= dict に key を入れない)。`analyze_status` field 新設 (= "pending" / "ready" / "failed") |
| `staged_pipeline.py:248-275`                      | `run_script(screenplay, screenplay_name, ts_path, ...)`            | str 必須                                                                                                                           | str 前提                                                                                     | **既存呼出経路 (= template 経由) はそのまま str を渡す**。Phase A の新 endpoint は run_script を呼ばない (= analyze save phase で別経路)                                                                                       |
| `staged_pipeline.py:369-446`                      | `run_overlay(screenplay, screenplay_name, ts_path)`                | `screenplay_name` を post caption ファイル名に使う (= line 416 `generate_post_captions(screenplay, screenplay_name, output_path)`) | None なら post_captions_gen.py:9 で `os.path.splitext(os.path.basename(None))` が TypeError  | **Stage 6 到達時点では analyze save が完了済 = `screenplay_name` は必ず str 確定** (Stage 0→1 unlock 条件)。docstring に「analyze 経由 project では Stage 0 完了で screenplay_name が決まる前提」を明記                        |
| `staged_pipeline.py:511-540`                      | `run_next_stage(screenplay, screenplay_name, ts_path)`             | str を per-stage runner に flow                                                                                                    | str 前提                                                                                     | overlay 同様、Stage 0 完了後にしか呼ばれない (= Stage 1 unlock 後) ので変更不要。ただし呼出側 (`routes/stages.py`) で `name` が None なら 400 error (= Stage 0 未完了) を返すガードを追加                                      |
| `staged_pipeline.py:702-733`                      | `regen(stage, ..., screenplay_name=None)`                          | overlay 以外は None 許容、overlay は str 必須                                                                                      | 既存ガード (`if screenplay_name is None: raise ValueError`) で OK                            | 変更不要                                                                                                                                                                                                                       |
| `routes/_helpers.py:160-162`                      | `load_screenplay_for_project(ts, ...)`                             | `name = meta.get("screenplay_template_name") or meta.get("screenplay_name")`, 無ければ 404 abort                                   | **Stage 0 中 (= screenplay_name=None) で Stage 1+ stage runner が起動されると 404**          | **403 ANALYZE_STAGE_NOT_READY を返す helper を追加** (= analyze pending を意図的に表現)。abort 404 は誤解を招く。404 → 403/error_code に切替                                                                                   |
| `routes/projects.py:33-38`                        | `_list_screenplays()`                                              | screenplays/ ディレクトリを ls。template 一覧用                                                                                    | metadata 読まないので影響なし                                                                | 変更不要                                                                                                                                                                                                                       |
| `routes/projects.py:62-80`                        | `_project_display_title(screenplay, screenplay_name)`              | `screenplay_name: str                                                                                                              | None` を受け取り、`auto\_<sha>` プレフィクスで「参考動画 <prefix>」に整形                    | **既に None ハンドリング済み**。caption も無ければ `(無題)`                                                                                                                                                                    | 変更不要                                                                                                                                                                             |
| `routes/projects.py:111-130`                      | `api_projects()` の per-project ループ                             | `meta.get("screenplay_name")` を `_project_display_title` に渡す                                                                   | None 許容済                                                                                  | **追加で `analyze_status` / `analyze_job_id` を response に含める** (= フロントの state バッジ用)                                                                                                                              |
| `routes/projects.py:134-166`                      | `api_create_project()` (= 既存 template 経由)                      | body の `screenplay_name` 必須 (line 144)                                                                                          | str 前提                                                                                     | 変更不要 (= 量産経路 #2 はそのまま str)                                                                                                                                                                                        |
| `routes/projects.py:169-185`                      | `api_project_detail()`                                             | `screenplay_name=name` を返す (`name` は `load_screenplay_for_project` から)                                                       | Stage 0 中なら 404 abort してしまう                                                          | **load_screenplay_for_project 失敗時の分岐を入れる**: metadata だけある + analyze pending なら `screenplay_name=null, analyze_status="pending"` で 200 を返す                                                                  |
| `scripts/ingest_video.py:77-84`                   | `main()`                                                           | `meta["screenplay_path"]` (= "screenplay.json") を解決して analytics DB に登録                                                     | `screenplay_name` ではなく `screenplay_path` を見る                                          | **Stage 0 中の project は `temp/<TS>/screenplay.json` 不在 → ingest 不可**。呼出元は Stage 8 完了後だけなので影響なし。ただし `meta["screenplay_path"]` が無いケースの defensive 化 (= meta.get で fallback してエラー) を追加 |
| `scripts/ingest_screenplay.py:35-58`              | `main()`                                                           | argv で screenplay path を直接受ける                                                                                               | metadata は使わない                                                                          | 変更不要                                                                                                                                                                                                                       |
| `scripts/dashboard.py:122`                        | `overview_tab()`                                                   | `perf` DataFrame の `screenplay_name` 列 (= analytics DB の v_performance view から)                                               | metadata.json は読まない                                                                     | 変更不要                                                                                                                                                                                                                       |
| `scripts/backfill_analyze_job_id.py:67`           | `main()`                                                           | `meta.get("screenplay_name") or ""` で逆引き                                                                                       | None なら空文字 → match なし                                                                 | **既存 dryrun の挙動は変わらない** (skip するだけ)。変更不要                                                                                                                                                                   |
| `scripts/migrate_to_project_snapshot.py:73-83`    | `_migrate_one()`                                                   | `meta.get("screenplay_template_name") or meta.get("screenplay_name") or os.path.basename(src)` の 3 段 fallback                    | 既に nullable 対応済                                                                         | 変更不要                                                                                                                                                                                                                       |
| `scripts/auto_loop.py:135-143, 267-277`           | `_create_project(sp_name)` / `_retry_stage(sp_name, ...)`          | str 前提                                                                                                                           | str 前提                                                                                     | 変更不要 (= template 経由経路だけ通る)                                                                                                                                                                                         |
| `screenplay_validator.py:802-833`                 | `validate_screenplay(screenplay, ...)`                             | screenplay dict (= metadata と独立) を見る                                                                                         | 影響なし                                                                                     | 変更不要                                                                                                                                                                                                                       |
| `final_import/publish.py:553`                     | `read_post_caption_for_ts(ts)`                                     | `meta.get("screenplay_name") or meta.get("screenplay_template_name") or ""`                                                        | 既に nullable 対応済                                                                         | 変更不要                                                                                                                                                                                                                       |
| `frontend/src/types.ts:140, 152`                  | `ProjectListItem.screenplay_name`, `ProjectDetail.screenplay_name` | `string`                                                                                                                           | None なら TypeScript で型エラー                                                              | \*\*`string                                                                                                                                                                                                                    | null`に変更**、追加で`analyze_status?: "pending"                                                                                                                                     | "running" | "completed" | "failed"`, `analyze_job_id?: string | null` を追加 |
| `frontend/src/components/ProjectShell.tsx:176`    | header に `{detail.screenplay_name}` 表示                          | str                                                                                                                                | None なら React で空 (= 安全だが UX 微妙)                                                    | **`detail.screenplay_name ?? "(分析中)"` で null 表示**。analyze_status="pending" なら badge も追加                                                                                                                            |
| `frontend/src/components/ProjectList.tsx:113-152` | `ProjectList()`                                                    | `p.screenplay_name` を直接 render しない (= `display_title` だけ表示)                                                              | 影響なし                                                                                     | 変更不要 (display_title は既に backend で計算済)                                                                                                                                                                               |
| `frontend/src/api.ts:123-130`                     | `createProject(screenplay_name, analyzeJobId?)`                    | str 引数                                                                                                                           | str 前提                                                                                     | **変更不要**。新エンドポイント `createProjectFromReferenceVideo` を別 method として追加                                                                                                                                        |
| `tests/test_preview_server_*.py` 多数             | metadata fixture が `screenplay_name=str` 前提                     | str                                                                                                                                | None 受入 test を別途追加                                                                    | 既存 fixture は触らず、Phase A の新 test は別ファイル `tests/test_routes_projects_from_reference_video.py` に置く                                                                                                              |

### A.2 結論

- `metadata.screenplay_name` の nullable 化は **追加 field と defensive helper の追加で済む**。既存の str 前提箇所はほぼ「Stage 0 完了後にしか呼ばれないコードパス」なので、Stage 0 unlock 条件を `progress_store` で表現すれば壊れない。
- 設計 §7.5 で「`null` または `"pending"` を許容する分岐を追加するか、別フィールド (= `analyze_status`) で「pending」を表現するか」とあったが、**両方採用する** (= 最も曖昧性が少ない):
  - `screenplay_name = null` (= 「決まっていない」を null で表現)
  - `analyze_status = "pending" | "running" | "completed" | "failed"` (= Stage 0 の状態を 1 field に集約)

### A.3 `analyze_status` を `progress_store` ではなく `metadata.json` に置く理由

設計 §5.2 で「`progress_store` に新しい stage key `analyze` を追加」とあるが、実装上の判断は **両方に書く** が **SSOT は `progress_store`**:

- `progress_store["stages"]["analyze"] = {"generated_at", "approved_at", "regen_count"}` (= 既存 stage と同じ schema)
- `metadata.json.analyze_status` は **キャッシュ的な dup**。`api_projects` でループするとき、毎 project 毎に `progress_store.load(ts_path)` を呼ぶのは重い (= `_list_screenplays + scandir + json.load` が既に走っているのでもう 1 回 disk seek)
- ただし `progress_store` を更新したら `metadata.json` も同期する責務が発生 → 1 つの場所に絞る
- **結論: `progress_store` のみ**。`api_projects` のレスポンスには `progress_store.load(ts_path)["stages"]["analyze"]` を読んで集約する (= 既に load している)

---

## B. 各 Phase の実装詳細

---

### Phase A: backend (`POST /api/projects/from-reference-video`)

#### A.1 変更ファイル一覧

- `routes/projects.py`: 新エンドポイント追加 + `api_projects` レスポンス拡張 + `api_project_detail` の defensive 化
- `routes/_helpers.py`: `load_screenplay_for_project` の Stage 0 中の挙動を分岐 + 新 helper `is_analyze_pending` 追加
- `staged_pipeline.py`: `write_metadata` を nullable 対応 + `init_pending_metadata` helper 新設
- `progress_store.py`: STAGES に `"analyze"` を追加 (先頭)、`mark_analyze_started` / `mark_analyze_completed` / `mark_analyze_failed` helper 追加
- `analyze/runner.py`: ジョブ完了時に project metadata + snapshot 同期する hook を追加
- `analyze/job.py`: ジョブに `project_ts: str | None` 列を追加 (= ジョブ → project の back link)
- `analytics/db.py` (= `analyze_jobs` schema 更新): `project_ts TEXT` カラム追加 (`init_db` の `CREATE TABLE IF NOT EXISTS` 内)
- `preview_server.py`: 起動時の `_analytics_db.init_db()` で schema migration 自動 (= 既存挙動)

#### A.2 関数単位の変更

##### A.2.1 `progress_store.STAGES` 拡張

`/Users/hirotaka/Projects/short_movie_generator/progress_store.py:6-12`:

```python
# 変更前
STAGES = [
    "script", "tts", "bg", "kling", "scene", "overlay",
    "final_import", "publish",
]

# 変更後
STAGES = [
    "analyze",  # NEW: Stage 0
    "script", "tts", "bg", "kling", "scene", "overlay",
    "final_import", "publish",
]
```

これにより:

- `progress_store.load(ts_path)["stages"]["analyze"]` が機能
- `progress_store.next_stage()` の最初の候補が `analyze` になる (= analyze 未起動の project は `next_stage="analyze"`)
- **既存 project (= analyze stage を持たない) は `_empty()` で初期化されるので、`progress.json` を持つ古い project は自動的に `analyze: {generated_at: None, approved_at: None}` で出現** (= `load` の `base["stages"].update(data.get("stages") or {})` の挙動より)

`progress_store._CASCADE_STAGES` (line 154) は変更しない (= analyze は cascade reset 対象外、独立した Stage 0)。

##### A.2.2 `progress_store` への新 helper 追加

新規追加 (line 50 周辺、`mark_generated` / `mark_approved` の隣):

```python
def mark_analyze_started(ts_path: str) -> None:
    """Stage 0 (analyze) を running 状態にする。
    既存 helper との対称性のため、generated_at は時刻、approved_at は None。
    """
    progress = load(ts_path)
    progress["stages"]["analyze"] = {
        "generated_at": _now(),
        "approved_at": None,
        "regen_count": 0,
        "status": "running",
    }
    save(ts_path, progress)


def mark_analyze_completed(ts_path: str) -> None:
    """Stage 0 (analyze) save phase 完了 → Stage 1 unlock。
    既存の `mark_generated` + `mark_approved` を 1 度に呼ぶ。analyze は
    人間 confirm 不要 (= save 完了 = 自動承認) なので approved_at もここで立てる。
    """
    progress = load(ts_path)
    now = _now()
    progress["stages"]["analyze"] = {
        "generated_at": now,
        "approved_at": now,
        "regen_count": 0,
        "status": "completed",
    }
    save(ts_path, progress)


def mark_analyze_failed(ts_path: str, error: str) -> None:
    """Stage 0 (analyze) を failed 状態にする。retry / 削除を UI で選択可能にする。"""
    progress = load(ts_path)
    progress["stages"]["analyze"] = {
        "generated_at": _now(),
        "approved_at": None,
        "regen_count": 0,
        "status": "failed",
        "error": error[:500],  # 長すぎる error は切る
    }
    save(ts_path, progress)


def analyze_status(ts_path: str) -> str | None:
    """Stage 0 (analyze) の現在状態を返す。"pending" | "running" | "completed" | "failed" | None。
    None は "Stage 0 を経由しない project" (= 既存 template 経由) を意味する。
    """
    progress = load(ts_path)
    block = progress["stages"].get("analyze") or {}
    return block.get("status")
```

##### A.2.3 `staged_pipeline.write_metadata` の nullable 対応

`/Users/hirotaka/Projects/short_movie_generator/staged_pipeline.py:208-235`:

変更前 (現状):

```python
def write_metadata(temp_dir: str, screenplay_name: str,
                    analyze_job_id: str | None = None,
                    sha256: str | None = None) -> None:
    # ...
    meta: dict = {
        "screenplay_name": screenplay_name,
        "screenplay_template_name": screenplay_name,
        # ...
    }
```

変更後:

```python
def write_metadata(temp_dir: str, screenplay_name: str | None,
                    analyze_job_id: str | None = None,
                    sha256: str | None = None) -> None:
    """project 作成時の metadata.json を書く。

    screenplay_name=None は **Stage 0 (analyze) 進行中** の状態を表す。
    save phase 完了時に `init_pending_metadata` の後続で書き換えられて
    auto_<sha>.json が入る。Stage 1+ stage runner は screenplay_name=None の
    metadata を受けると 403 ANALYZE_STAGE_NOT_READY で reject する。
    """
    if sha256 is None:
        snap = project_screenplay_path(temp_dir)
        if os.path.exists(snap):
            with open(snap, "rb") as f:
                sha256 = hashlib.sha256(f.read()).hexdigest()
    meta: dict = {
        "screenplay_path": PROJECT_SCREENPLAY_FILENAME,
        "screenplay_sha256": sha256 or "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if screenplay_name:
        # analyze 完了後 / 既存 template 経由は str を持つ
        meta["screenplay_name"] = screenplay_name
        meta["screenplay_template_name"] = screenplay_name
    if analyze_job_id:
        meta["analyze_job_id"] = analyze_job_id
    os.makedirs(temp_dir, exist_ok=True)
    io_utils.atomic_write_json(
        os.path.join(temp_dir, "metadata.json"), meta,
    )
```

##### A.2.4 新 helper `init_pending_metadata` 追加

`staged_pipeline.py` の `write_metadata` の直後に追加:

```python
def init_pending_metadata(temp_dir: str, analyze_job_id: str) -> None:
    """Stage 0 開始時の metadata.json 初期化。

    `screenplay_name`, `screenplay_template_name`, `screenplay_path`,
    `screenplay_sha256` は全て omit (= 後で update する)。`analyze_job_id`
    と `created_at` だけ書く。

    save phase 完了 hook (= analyze.runner._on_save_complete) が
    `update_metadata_after_analyze` を呼んで残りを埋める。
    """
    os.makedirs(temp_dir, exist_ok=True)
    meta = {
        "analyze_job_id": analyze_job_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    io_utils.atomic_write_json(
        os.path.join(temp_dir, "metadata.json"), meta,
    )


def update_metadata_after_analyze(
    temp_dir: str, screenplay_name: str, sha256: str,
) -> None:
    """analyze save phase 完了 hook から呼ばれる。

    metadata.json に screenplay_name / screenplay_template_name /
    screenplay_path / screenplay_sha256 を書き足す (= 既存 analyze_job_id /
    created_at は維持)。
    """
    from project_state import read_metadata
    meta = read_metadata(temp_dir) or {}
    meta["screenplay_name"] = screenplay_name
    meta["screenplay_template_name"] = screenplay_name
    meta["screenplay_path"] = PROJECT_SCREENPLAY_FILENAME
    meta["screenplay_sha256"] = sha256
    io_utils.atomic_write_json(
        os.path.join(temp_dir, "metadata.json"), meta,
    )
```

##### A.2.5 `analyze/job.py` に `project_ts` 列追加

`/Users/hirotaka/Projects/short_movie_generator/analyze/job.py:65-90` (`AnalyzeJob` dataclass):

```python
@dataclass
class AnalyzeJob:
    id: str
    video_sha256: str
    options_json: str
    status: str
    current_phase: str | None = None
    error: str | None = None
    estimated_cost_usd: float | None = None
    actual_cost_usd: float | None = None
    screenplay_path: str | None = None
    style_name: str | None = None
    project_ts: str | None = None  # NEW: project に紐付いていれば TS、独立なら None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    cancellation_requested: int = 0
```

`create_job` のシグネチャ更新 (line 104):

```python
def create_job(
    video_sha256: str,
    options: dict,
    *,
    project_ts: str | None = None,  # NEW
) -> AnalyzeJob:
    """新規 analyze ジョブを作成し PHASES の行も初期化する。

    project_ts: Stage 0 経路で呼ばれた場合、新規 project の TS を渡す。
    save phase 完了時に hook がこの project の metadata + snapshot を
    更新する。None は test-only (= production の caller である POST
    /api/projects/from-reference-video は必ず project_ts を渡す。
    旧 standalone analyze 経路は Phase E (#182) で削除済)。
    """
    job_id = _new_job_id()
    options_json = json.dumps(options, ensure_ascii=False, sort_keys=True)
    created_at = _now()

    with _db.get_connection() as conn:
        conn.execute(
            """INSERT INTO analyze_jobs
               (id, video_sha256, options_json, status, project_ts, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (job_id, video_sha256, options_json, "pending",
             project_ts, created_at),
        )
        for phase in PHASES:
            conn.execute(
                """INSERT INTO analyze_phases (job_id, phase, status)
                   VALUES (?, ?, ?)""",
                (job_id, phase, "pending"),
            )
    logger.info("analyze job created: %s (video=%s, project_ts=%s)",
                job_id, video_sha256[:12], project_ts)
    return get_job(job_id)
```

##### A.2.6 `analytics/db.py` schema migration

`init_db()` 内の `analyze_jobs` の CREATE TABLE IF NOT EXISTS に `project_ts TEXT` を追加。**既存 DB に対しては `ALTER TABLE` migration が必要** (= IF NOT EXISTS は新規作成時のみ列を反映):

```python
# analytics/db.py の init_db() 内 (現状を確認):
# CREATE TABLE IF NOT EXISTS analyze_jobs (...)

# 末尾に追加 (= 冪等な migration block):
def _migrate_add_project_ts(conn) -> None:
    """analyze_jobs.project_ts 列を後付け。冪等。"""
    cols = {row["name"] for row in conn.execute(
        "PRAGMA table_info(analyze_jobs)"
    ).fetchall()}
    if "project_ts" not in cols:
        conn.execute("ALTER TABLE analyze_jobs ADD COLUMN project_ts TEXT")
```

##### A.2.7 `analyze/runner.py` の save phase 完了 hook 追加

`/Users/hirotaka/Projects/short_movie_generator/analyze/runner.py:71-127` の `_PhaseTracker.handle()` に save phase 完了処理を追加:

```python
class _PhaseTracker:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.phase_start_times: dict[str, float] = {}

    def handle(self, event: str, data: dict) -> None:
        phase = data.get("phase")
        # ... 既存コード ...
        elif event == "phase_complete" and phase == "save":
            # 通常の duration 記録の後に project hook を発火
            started = self.phase_start_times.get(phase)
            duration_ms = int((time.time() - started) * 1000) if started else None
            try:
                job.complete_phase(self.job_id, phase, duration_ms=duration_ms)
            except Exception:
                logger.exception("complete_phase failed: %s/%s",
                                 self.job_id, phase)
            # NEW: project hook
            self._on_save_complete(data)
        elif event == "phase_complete" and phase:
            # ... 既存コード ...
        # ...

    def _on_save_complete(self, data: dict) -> None:
        """analyze save phase 完了時に project metadata + snapshot を更新する。

        project_ts が紐付いていれば:
          1. screenplays/auto_<sha>.json (= analyze 出力) を読む
          2. temp/<TS>/screenplay.json に snapshot コピー
          3. metadata.json に screenplay_name / sha256 を書き足す
          4. progress_store.mark_analyze_completed で Stage 0 完了

        project_ts=None (= 旧 standalone 経路) なら no-op (= Phase E で削除)。
        """
        try:
            j = job.get_job(self.job_id)
        except KeyError:
            logger.warning("save hook: job not found: %s", self.job_id)
            return
        if not j.project_ts:
            return  # standalone analyze, no project to update

        output_path = data.get("output_path")
        if not output_path or not os.path.exists(output_path):
            logger.error("save hook: output_path missing: %s", output_path)
            return

        import config
        ts_path = os.path.join(config.TEMP_DIR, j.project_ts)
        if not os.path.isdir(ts_path):
            logger.error("save hook: project not found: %s", ts_path)
            return

        try:
            import shutil
            import staged_pipeline
            # 1. snapshot として temp/<TS>/screenplay.json にコピー
            snap_path = staged_pipeline.project_screenplay_path(ts_path)
            shutil.copyfile(output_path, snap_path)
            with open(snap_path, "rb") as f:
                sha256 = hashlib.sha256(f.read()).hexdigest()
            # 2. metadata.json 更新
            screenplay_name = os.path.basename(output_path)
            staged_pipeline.update_metadata_after_analyze(
                ts_path, screenplay_name, sha256,
            )
            # 3. Stage 0 完了 mark + Stage 1 (script) も auto-mark
            #    (= load_template の代わりに snapshot を使うので script step は no-op)
            import progress_store
            progress_store.mark_analyze_completed(ts_path)
            progress_store.mark_generated(ts_path, "script")
            progress_store.mark_approved(ts_path, "script")
            logger.info("[save-hook] project %s unlocked Stage 1 (sp=%s)",
                        j.project_ts, screenplay_name)
        except Exception:
            logger.exception("save hook failed for %s", j.project_ts)
            # 失敗しても analyze 自体は成功扱い (= screenplay.json は残る)
            # Phase B の UI が「Stage 0 完了したけど project hook 失敗」を
            # 表示するため、metadata に hook_error を書く
            try:
                from project_state import read_metadata
                meta = read_metadata(ts_path) or {}
                meta["analyze_hook_error"] = "save hook failed (see server log)"
                io_utils.atomic_write_json(
                    os.path.join(ts_path, "metadata.json"), meta,
                )
            except Exception:
                logger.exception("write hook_error failed")
```

加えて、`_run_job_impl` (line 196-245) の最後に **failed / cancelled 時も progress_store に書く**:

```python
def _run_job_impl(job_id: str) -> None:
    j = job.get_job(job_id)
    # ... 既存コード ...
    try:
        screenplay = pipeline.run(...)
        # ... 既存 completed 遷移 ...
    except CostGateTimeout:
        # NEW: project hook
        if j.project_ts:
            _mark_project_analyze_failed(j.project_ts, "cost gate timeout")
        return
    except AnalyzeCancelled:
        job.transition_status(job_id, "cancelled")
        progress.publish(job_id, "cancelled", {})
        # NEW: project hook
        if j.project_ts:
            _mark_project_analyze_failed(j.project_ts, "cancelled by user")


def _mark_project_analyze_failed(project_ts: str, reason: str) -> None:
    """project の Stage 0 を failed 状態にする (cancellation / timeout / runner error)。"""
    import config
    import progress_store
    ts_path = os.path.join(config.TEMP_DIR, project_ts)
    if os.path.isdir(ts_path):
        try:
            progress_store.mark_analyze_failed(ts_path, reason)
        except Exception:
            logger.exception(
                "mark_analyze_failed failed for %s", project_ts,
            )
```

`_run_job` の `except Exception` ブロック (line 186-193) も同じ `_mark_project_analyze_failed` を呼ぶよう更新する。

##### A.2.8 `routes/projects.py` に新エンドポイント追加

`/Users/hirotaka/Projects/short_movie_generator/routes/projects.py` の `api_create_project` (line 134) の後に追加:

```python
@projects_bp.route("/api/projects/from-reference-video", methods=["POST"])
def api_create_project_from_reference_video():
    """参考動画 + analyze ジョブを 1 トランザクションで起動する (= 主導フロー)。

    multipart/form-data で動画を受け取り、reference_videos へ dedup 登録、
    新 project (= temp/<TS>/) を作成、analyze ジョブを enqueue する。
    save phase 完了時に runner._on_save_complete が project metadata と
    Stage 1 unlock を行う (= 設計 §3.1)。

    Body (multipart):
      - reference_video: file (.mov / .mp4 / .webm / .mkv, ≤ MAX_CONTENT_LENGTH)
      - instructions: optional string (= analyze.options.instructions)
      - fps: optional float (default 2.0)

    Response (201):
      { "ts": "<TS>", "analyze_job_id": "analyze_<...>" }

    Side effects:
      1. assets/reference_videos/<sha>.<ext> に dedup 保存 (= 既存挙動)
      2. analyze_jobs に project_ts=<TS> 付きで insert
      3. temp/<TS>/metadata.json を screenplay_name=null で初期化
      4. progress_store.mark_analyze_started で Stage 0 = running
      5. analyze.runner.start で daemon thread 起動
    """
    from analyze import job as analyze_job
    from analyze import runner as analyze_runner
    from analyze.cache import file_sha256
    import uuid

    f = request.files.get("reference_video")
    if not f:
        return jsonify({
            "error_code": "REFERENCE_VIDEO_REQUIRED",
            "message": "reference_video (multipart) is required",
        }), 400

    name = f.filename or "video"
    ext = os.path.splitext(name)[1].lower()
    if ext not in analyze_job.ALLOWED_VIDEO_EXTS:
        return jsonify({
            "error_code": "REFERENCE_VIDEO_UNSUPPORTED_EXT",
            "message": f"unsupported extension: {ext}",
            "allowed": list(analyze_job.ALLOWED_VIDEO_EXTS),
        }), 400

    # 1. reference video upload (= dedup 込み)。
    # preview_server.api_upload_reference_video のロジックを共有 helper に
    # 切り出すのが本来は綺麗だが、Phase A スコープを抑えるためコピペで実装する。
    # Phase E の旧経路削除時に共通化 (= 設計 §6 Phase E)。
    ref_dir = analyze_job.reference_videos_dir()
    tmp = ref_dir / f".tmp_{uuid.uuid4().hex}{ext}"
    sha = ""
    duration = None
    try:
        f.save(str(tmp))
        sha = file_sha256(str(tmp))
        size = os.path.getsize(tmp)
        existing = analyze_job.get_reference_video(sha)
        if existing:
            tmp.unlink(missing_ok=True)
            analyze_job.touch_reference_video(sha)
        else:
            final_path = ref_dir / f"{sha}{ext}"
            tmp.replace(final_path)
            from preview_server import _ffprobe_duration
            duration = _ffprobe_duration(str(final_path))
            analyze_job.upsert_reference_video(
                sha, original_name=os.path.basename(name),
                size_bytes=size, duration_sec=duration,
            )
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)

    # 2. options 抽出 (= /api/screenplay/analyze と同じ filter)
    options: dict = {}
    instr = (request.form.get("instructions") or "").strip()
    if instr:
        options["instructions"] = instr
    fps_raw = request.form.get("fps")
    if fps_raw:
        try:
            options["fps"] = float(fps_raw)
        except ValueError:
            return jsonify({
                "error_code": "ANALYZE_INVALID_FPS",
                "message": f"invalid fps: {fps_raw}",
            }), 400

    # 3. project TS 発行 + 初期化
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_path = ts_path(ts)
    os.makedirs(project_path, exist_ok=True)

    # 4. analyze ジョブ create (project_ts 紐付け)
    j = analyze_job.create_job(sha, options, project_ts=ts)

    # 5. metadata.json + progress.json 初期化
    staged_pipeline.init_pending_metadata(project_path, j.id)
    progress_store.mark_analyze_started(project_path)

    # 6. runner.start で daemon thread 起動 (= save 完了で hook 発火)
    analyze_runner.start(j.id)

    return jsonify({
        "ts": ts,
        "analyze_job_id": j.id,
    }), 201
```

##### A.2.9 `routes/projects.py::api_projects` レスポンス拡張

line 120-130 を修正:

```python
items.append({
    "timestamp": ts,
    "screenplay_name": meta.get("screenplay_name"),
    "display_title": title,
    "caption_hashtags": hashtags,
    "scene_count": scene_count,
    "has_bg_thumbnail": has_bg_thumbnail,
    "created_at": meta.get("created_at"),
    "current_stage": progress_store.current_stage(project_path),
    "progress": progress,
    # NEW: Stage 0 のバッジ表示用
    "analyze_status": progress_store.analyze_status(project_path),
    "analyze_job_id": meta.get("analyze_job_id"),
})
```

##### A.2.10 `routes/projects.py::api_project_detail` の defensive 化

line 169-185 (`api_project_detail`) を修正:

```python
@projects_bp.route("/api/projects/<ts>", methods=["GET"])
def api_project_detail(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    meta = staged_pipeline.read_metadata(project_path) or {}
    progress = progress_store.load(project_path)
    analyze_status_val = progress_store.analyze_status(project_path)

    # Stage 0 中 (= snapshot 不在) は screenplay = null で 200 を返す
    sp = None
    name = None
    if meta.get("screenplay_name"):
        try:
            sp, name = load_screenplay_for_project(ts)
        except Exception as e:
            logger.warning("screenplay load failed for %s: %s", ts, e)

    return jsonify({
        "timestamp": ts,
        "screenplay_name": name,  # None なら null
        "screenplay": sp,         # None なら null
        "progress": progress,
        "current_stage": progress_store.current_stage(project_path),
        "analyze_job_id": meta.get("analyze_job_id"),
        "analyze_status": analyze_status_val,
    })
```

##### A.2.11 `routes/_helpers.py::load_screenplay_for_project` の挙動

line 143-167 は変更しない (= 既存呼出元 = `api_run_next` / `api_regen` / `api_tts_source` 等が 404 abort で適切に reject される)。**ただし** `api_project_detail` (上記 A.2.10) のように **404 ではなく Stage 0 中の表示を返すべき** 呼出元は **個別に if-check してから呼ぶ**。

新 helper を追加 (`routes/_helpers.py` 末尾、line 168 以降):

```python
def is_analyze_pending(ts: str, *, temp_dir: str | None = None) -> bool:
    """指定 project が Stage 0 (analyze) 中かどうか。

    `screenplay_name` が None かつ `analyze_status` が None / "pending" /
    "running" なら True。

    呼出側: api_project_detail / api_get_project_abstract / api_run_next 等
    で 404 を返す前に呼んで、403 ANALYZE_STAGE_NOT_READY に切替えるか判定。
    """
    import progress_store
    import staged_pipeline
    project_path = ts_path(ts, temp_dir=temp_dir)
    meta = staged_pipeline.read_metadata(project_path) or {}
    if meta.get("screenplay_name"):
        return False
    status = progress_store.analyze_status(project_path)
    return status in (None, "pending", "running")
```

#### A.3 テスト方針

##### A.3.1 backend unit / integration tests

新規テストファイル `tests/test_routes_projects_from_reference_video.py`:

- `test_create_from_reference_video_returns_ts_and_job_id`: multipart で動画を POST し、201 + `{ts, analyze_job_id}` を返す。`temp/<TS>/metadata.json` が `screenplay_name` 不在 + `analyze_job_id=<id>` で初期化される。
- `test_create_from_reference_video_dedup_existing`: 同一 sha256 を 2 回 POST、2 回目は既存 reference_video を流用する (= `assets/reference_videos/<sha>.<ext>` が 1 個だけ)。ただし新 project は別 TS で作られる。
- `test_create_from_reference_video_invalid_ext`: `.txt` などを送って 400 + `error_code=REFERENCE_VIDEO_UNSUPPORTED_EXT`。
- `test_create_from_reference_video_no_file`: file 無しで 400 + `error_code=REFERENCE_VIDEO_REQUIRED`。
- `test_progress_store_analyze_helpers`: `mark_analyze_started` → `started_at` set。`mark_analyze_completed` → `approved_at` set + status="completed"。`mark_analyze_failed` → status="failed" + error 記録。
- `test_save_hook_updates_metadata_and_unlocks_stage1`: `_PhaseTracker._on_save_complete` を直接呼んで、project metadata の `screenplay_name` が auto\_<sha>.json に、Stage 0 と Stage 1 が completed/approved になることを確認。
- `test_save_hook_handles_missing_project_ts`: `project_ts=None` のジョブで save 完了 → no-op (= raise しない、log のみ)。
- `test_save_hook_handles_failure_gracefully`: `shutil.copyfile` を mock で raise させ、analyze 自体は成功しても metadata に `analyze_hook_error` が書かれる。
- `test_init_pending_metadata_omits_screenplay_fields`: `screenplay_name` / `screenplay_template_name` / `screenplay_path` / `screenplay_sha256` が dict に存在しないこと。
- `test_update_metadata_after_analyze_preserves_existing`: `analyze_job_id` / `created_at` が上書きされない。

既存テストの更新:

- `tests/test_preview_server_project_list.py:142-157` の `test_projects_falls_back_to_filename_when_caption_missing` は `screenplay_name=str` 前提のままで OK (= 既存 template 経由の test、変更不要)。
- `tests/test_routes_helpers.py` に `is_analyze_pending` のテスト追加。

##### A.3.2 既存 fixture の影響

`tests/test_preview_server_*.py` の多くが `staged_pipeline.run_script(screenplay, "test.json", str(ts_path))` で project を作る。これは **既存 template 経由** = `screenplay_name=str` を維持 (= `write_metadata` の str 引数経路)。Phase A の変更は **追加経路** なので、既存 fixture は触らない。

##### A.3.3 progress_store STAGES 追加によるテスト影響

`progress_store.STAGES` に `"analyze"` を先頭追加すると:

- `tests/test_progress_store_*.py` で `STAGES` を参照しているテストが影響を受ける
- `test_next_stage_returns_first_unrun_stage` 系が「最初の stage = script」前提で書かれている可能性 → **`script` が next_stage になるためには Stage 0 が approved 済みである必要がある**

事前確認:
<br>

```bash
grep -rn "STAGES\b\|next_stage\|first stage" tests/test_progress_store*.py
```

→ 影響テストを Phase A の最初に grep 監査して、必要なら fixture で `progress_store.mark_analyze_completed(ts_path)` を先に呼んで Stage 0 を skip させる helper を共通化する (= `tests/conftest.py` に `_skip_analyze_stage_for_legacy_project` を追加)。

#### A.4 Acceptance criteria

1. `POST /api/projects/from-reference-video` (multipart) が 201 + `{ts, analyze_job_id}` を返す
2. `temp/<TS>/metadata.json` が `screenplay_name` 不在 + `analyze_job_id` 付きで初期化される
3. `temp/<TS>/tmp-progress.json` の `stages.analyze.status` が `"running"` で初期化される
4. analyze daemon thread が起動している (= `analyze.runner.start` が呼ばれた)
5. analyze save phase 完了時に `temp/<TS>/screenplay.json` (snapshot) と `screenplays/auto_<sha>.json` (template) の両方が同一 SHA256 で存在する
6. save 完了後、`metadata.json.screenplay_name = "auto_<sha>.json"`, `progress.stages.analyze.status = "completed"`, `progress.stages.script.approved_at != null`
7. `GET /api/projects` のレスポンスに `analyze_status` / `analyze_job_id` が含まれる
8. `GET /api/projects/<TS>` が Stage 0 中でも 200 を返す (= `screenplay_name=null, screenplay=null, analyze_status="running"`)
9. analyze 失敗 / cancel / cost-gate-timeout 時に `progress.stages.analyze.status = "failed"` になる
10. 既存の `POST /api/projects` (= screenplay_name + analyze_job_id) は無変更で動作する (= 後方互換)

---

### Phase B: frontend (Stage 0 page + 自動遷移)

#### B.1 変更ファイル一覧

- `frontend/src/App.tsx`: 新 route `/project/:ts/analyze` 追加 + ProjectShell の outlet 候補に追加
- `frontend/src/components/AnalyzeJobView.tsx`: project-internal モード prop 追加 + 完了時自動遷移実装
- `frontend/src/api.ts`: 新 method `createProjectFromReferenceVideo` 追加
- `frontend/src/types.ts`: `ProjectListItem` / `ProjectDetail` の `screenplay_name` を nullable 化、`analyze_status` 追加
- `frontend/src/pages/AnalyzeStage0Page.tsx` (新規): `/project/<TS>/analyze` の page component
- `frontend/src/components/ProjectShell.tsx`: header の `screenplay_name` null 表示対応 + Stage 0 中の loadProgress 制御
- `frontend/src/components/StageProgressBar.tsx`: STAGES 配列の先頭に `{key: "analyze", label: "分析"}` 追加 (= Stage 0 表示)

#### B.2 関数単位の変更

##### B.2.1 `frontend/src/api.ts` に新 method

`/Users/hirotaka/Projects/short_movie_generator/frontend/src/api.ts:280-310` (`uploadReferenceVideo` の隣) に追加:

```typescript
// ─── 主導フロー: 参考動画から新 project を作成 ──────
createProjectFromReferenceVideo: (
  file: File,
  options: { instructions?: string; fps?: number } = {},
  onProgress?: (pct: number) => void,
): Promise<{ ts: string; analyze_job_id: string }> => {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const fd = new FormData();
    fd.append("reference_video", file);
    if (options.instructions) fd.append("instructions", options.instructions);
    if (options.fps != null) fd.append("fps", String(options.fps));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(e.loaded / e.total);
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch (e) {
          reject(e instanceof Error ? e : new Error(String(e)));
        }
      } else {
        let body: unknown = undefined;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          // ignore
        }
        reject(new ApiError(xhr.status, xhr.responseText, body));
      }
    };
    xhr.onerror = () => reject(new Error("network error"));
    xhr.open("POST", `${API_BASE}/api/projects/from-reference-video`);
    applyAuthToXhr(xhr);
    xhr.send(fd);
  });
},
```

##### B.2.2 `frontend/src/types.ts` の更新

line 138-148 (`ProjectListItem`) と line 150-157 (`ProjectDetail`) を更新:

```typescript
export type AnalyzeStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | null;

export interface ProjectListItem {
  timestamp: string;
  screenplay_name: string | null; // CHANGE: was string
  display_title: string;
  caption_hashtags: string;
  scene_count: number;
  has_bg_thumbnail: boolean;
  created_at: string;
  current_stage: StageName | null;
  progress: Progress;
  // NEW
  analyze_status?: AnalyzeStageStatus;
  analyze_job_id?: string | null;
}

export interface ProjectDetail {
  timestamp: string;
  screenplay_name: string | null; // CHANGE
  screenplay: Screenplay | null; // CHANGE: was Screenplay (always present)
  progress: Progress;
  current_stage: StageName | null;
  analyze_job_id: string | null;
  // NEW
  analyze_status?: AnalyzeStageStatus;
}
```

`StageName` (line 1-9) には `"analyze"` を追加するか **しないか** を決める必要がある:

- **追加する**: ProjectShell の navigate / StageProgressBar が分かりやすい
- **追加しない**: `/project/<TS>/analyze` はあくまで Stage 0 専用 page で、stages フォルダ配下の StageScript / StageTTS とは別系統 (= UI 構造的に違う)

**結論: `StageName` は触らない**。`/project/<TS>/analyze` は ProjectShell の outlet ではなく **独立 page** として実装する (= 詳細は B.2.5)。

##### B.2.3 `frontend/src/components/AnalyzeJobView.tsx` の prop 拡張

line 82 のシグネチャを変更:

```typescript
// 変更前
export default function AnalyzeJobView({ jobId }: { jobId: string }) {

// 変更後
interface Props {
  jobId: string;
  /** Stage 0 page (= /project/<TS>/analyze) が渡す project の TS。
   * 完了時に `/project/<TS>/script` へ自動遷移する。
   * (Phase B 時点では `string | null` で standalone モードを残していたが、
   *  Phase E (#182) で旧モードを削除し必須化済。)
   */
  projectTs: string;
}

export default function AnalyzeJobView({ jobId, projectTs }: Props) {
```

完了処理 (line 612-702 の `completedPath` 表示ブロック) を分岐:

```tsx
{
  completedPath && screenplayName && (
    <div className="card border border-emerald-500/40">
      <h3 className="font-semibold mb-2 text-emerald-300">✓ 台本作成完了</h3>
      <div className="text-sm">
        台本: <span className="font-mono break-all">{completedPath}</span>
      </div>
      {/* ...summary blocks (jobStartedAt, annotationStats, suggestedIntents)... */}

      {projectTs ? (
        // project-internal モード: 自動遷移待ち
        <AutoNavigateOnComplete ts={projectTs} />
      ) : (
        // standalone モード (= 旧経路、Phase D で notice 追加 / Phase E で削除)
        <div className="mt-3 flex gap-2 flex-wrap">
          <button
            type="button"
            className="btn-primary"
            disabled={composing}
            onClick={async () => {
              // 既存の「プロジェクト作成」ボタンロジック (line 671-696)
              // ...
            }}
          >
            {composing ? "作成中…" : "プロジェクト作成 →"}
          </button>
          <Link to="/" className="btn-ghost">
            後で (プロジェクト一覧へ)
          </Link>
        </div>
      )}
      {/* ... */}
    </div>
  );
}
```

`AutoNavigateOnComplete` は AnalyzeJobView の同ファイル内に inline で定義:

```tsx
function AutoNavigateOnComplete({ ts }: { ts: string }) {
  const navigate = useNavigate();
  useEffect(() => {
    // 短い grace period を置く (= ユーザーが「完了!」を視認できるように)
    const t = window.setTimeout(() => {
      navigate(`/project/${ts}/script`);
    }, 1500);
    return () => window.clearTimeout(t);
  }, [navigate, ts]);
  return (
    <div className="mt-3 text-xs text-slate-400">
      Stage 1 (台本編集) に自動遷移します...
    </div>
  );
}
```

**注意**: `useEffect` での `setTimeout` ベース遷移は **save phase 完了 SSE event を受信してから 1500ms** 後に発火する。タイミングは:

1. backend save phase 完了 → `phase_complete` SSE event
2. AnalyzeJobView の `phase_complete` handler が `completedPath` を set
3. `completed` SSE event (= 全フェーズ完了) → AnalyzeJobView の `completed` handler が再度 `completedPath` を set + es.close()
4. backend の `_on_save_complete` hook が走り終わる (= metadata.json + snapshot + progress_store の更新)
5. UI 遷移

backend の hook が完了する前に遷移するとキャッシュ的に古い metadata を読んでしまう。**1500ms は経験的安全マージン**。長過ぎず短過ぎず (= ユーザーの「完了」視認時間としても適切)。

将来 (Phase B+1 改善) は backend hook 完了を表す SSE event を新設して、それを受信したら遷移するのが正しい。Phase B では setTimeout 方式で先行リリース。

##### B.2.4 `frontend/src/App.tsx` に新 route 追加

line 14-34 を拡張:

```tsx
import AnalyzeStage0Page from "./pages/AnalyzeStage0Page";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectList />} />
      <Route path="/analyze" element={<AnalyzePage />} />
      <Route path="/intent-catalog" element={<IntentCatalogPage />} />
      {/* NEW: Stage 0 page (= ProjectShell の outlet ではない、独立) */}
      <Route path="/project/:ts/analyze" element={<AnalyzeStage0Page />} />
      <Route path="/project/:ts" element={<ProjectShell />}>
        <Route index element={<Navigate to="script" replace />} />
        <Route path="script" element={<StageScript />} />
        {/* ... */}
      </Route>
    </Routes>
  );
}
```

ProjectShell の outlet 配下にしないのは、ProjectShell が `api.project(ts)` を初回ロードして `screenplay` を期待するため。Stage 0 中は `screenplay=null` で ProjectShell が壊れる。**Stage 0 page は独立 layout** (= 上に戻るリンクだけ持つ簡素な page)。

##### B.2.5 `frontend/src/pages/AnalyzeStage0Page.tsx` (新規)

```tsx
import { useEffect, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { api } from "../api";
import AnalyzeJobView from "../components/AnalyzeJobView";
import type { ProjectDetail } from "../types";

export default function AnalyzeStage0Page() {
  const { ts } = useParams<{ ts: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ts) return;
    let cancelled = false;
    api
      .project(ts)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        // Stage 0 が完了済みなら直接 Stage 1 へ
        if (d.analyze_status === "completed") {
          navigate(`/project/${ts}/script`, { replace: true });
        }
        // Stage 0 経由ではない project (= 既存 template 経由) なら Stage 1 へ
        if (d.analyze_status == null && d.screenplay_name) {
          navigate(`/project/${ts}/script`, { replace: true });
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [ts, navigate]);

  if (!ts) return <div>invalid project</div>;
  if (error) {
    return (
      <div className="container mx-auto p-6 max-w-3xl">
        <div className="card border border-rose-500/40 text-rose-200">
          {error}
        </div>
        <Link to="/" className="btn-ghost mt-4 inline-block">
          ← プロジェクト一覧
        </Link>
      </div>
    );
  }
  if (!detail) return <div className="p-6">読み込み中...</div>;

  return (
    <div className="container mx-auto p-6 max-w-3xl space-y-4">
      <header className="flex items-center justify-between">
        <Link to="/" className="text-sm text-slate-400 hover:text-emerald-400">
          ← プロジェクト一覧
        </Link>
        <h1 className="text-lg font-semibold">
          📹 参考動画を分析中
          <span className="ml-3 text-xs text-slate-400 font-mono">{ts}</span>
        </h1>
      </header>

      {detail.analyze_status === "failed" && <FailedActions ts={ts} />}
      {detail.analyze_job_id && detail.analyze_status !== "failed" && (
        <AnalyzeJobView jobId={detail.analyze_job_id} projectTs={ts} />
      )}
    </div>
  );
}

function FailedActions({ ts }: { ts: string }) {
  // 設計 §7.1 の候補 2: 失敗時に retry / 削除 / TOP に戻る を選べる
  const [busy, setBusy] = useState(false);
  return (
    <div className="card border border-rose-500/40">
      <h3 className="font-semibold text-rose-300 mb-2">⚠ 分析が失敗しました</h3>
      <p className="text-sm text-slate-300 mb-3">
        以下から選んでください。retry は cache が効くので追加課金は最小です。
      </p>
      <div className="flex gap-2 flex-wrap">
        <button
          className="btn-primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api.retryAnalyzeForProject(ts); // Phase A の追加 endpoint
              window.location.reload();
            } catch (e) {
              alert(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          🔁 リトライ
        </button>
        <button
          className="btn-ghost"
          disabled={busy}
          onClick={async () => {
            if (!confirm("このプロジェクトを削除しますか?")) return;
            setBusy(true);
            try {
              await api.deleteProject(ts); // Phase A 追加 endpoint
              window.location.href = "/";
            } catch (e) {
              alert(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          🗑 削除
        </button>
        <Link to="/" className="btn-ghost">
          後で (TOP に戻る)
        </Link>
      </div>
    </div>
  );
}
```

**注**: `api.retryAnalyzeForProject` と `api.deleteProject` の backend 実装も Phase A に含める。詳細は §D.1 (リスク対応) で記述。

##### B.2.6 `ProjectShell.tsx` の null 表示 + Stage 0 redirect

`/Users/hirotaka/Projects/short_movie_generator/frontend/src/components/ProjectShell.tsx` の load 部分を修正:

- `api.project(ts)` の結果 `analyze_status === "running" || "pending" || "failed"` なら `/project/<TS>/analyze` に redirect
- `screenplay_name` が null なら header に `(分析中)` を表示

具体的な変更箇所は ProjectShell の useEffect で project 詳細を fetch する部分 (line 番号は実際のコードに依存):

```tsx
useEffect(() => {
  // ...existing fetch logic...
  api.project(ts).then((d) => {
    setDetail(d);
    if (
      d.analyze_status === "running" ||
      d.analyze_status === "pending" ||
      d.analyze_status === "failed"
    ) {
      navigate(`/project/${ts}/analyze`, { replace: true });
    }
  });
}, [ts]);
```

header line 176:

```tsx
<h1 className="text-lg font-semibold mt-1">
  {detail.screenplay_name ?? "(分析中)"}
  <span className="ml-3 text-xs text-slate-400">{detail.timestamp}</span>
</h1>
```

##### B.2.7 `StageProgressBar.tsx` に Stage 0 表示

オプショナル (= 設計 §3 の Stage 0 を視覚的に示すため)。完了済みプロジェクト (= analyze_status="completed") では表示しても情報量が少ないので、**実装はスキップ可** (= Phase B+ で UX レビュー後に決定)。

#### B.3 テスト方針

##### B.3.1 frontend (vitest)

新規テストファイル `frontend/src/api.from-reference-video.test.ts`:

- `createProjectFromReferenceVideo` が multipart で POST し、response を返す
- options.instructions が form data に含まれる
- ApiError を throw する (= 4xx / 5xx)

新規テストファイル `frontend/src/components/AnalyzeJobView.test.tsx` (= 既存に追加):

- `projectTs` prop を渡すと `AutoNavigateOnComplete` が render される
- `projectTs` 不指定なら従来通り「プロジェクト作成」ボタンが render される
- `completedPath` が set されてから 1500ms 後に navigate が呼ばれる (= `vi.useFakeTimers`)

新規テストファイル `frontend/src/pages/AnalyzeStage0Page.test.tsx`:

- analyze_status="completed" なら自動で `/project/<TS>/script` に redirect
- analyze_status="failed" なら FailedActions が表示される
- analyze_status="running" なら AnalyzeJobView が表示される

##### B.3.2 e2e (= playwright が無ければ手動テスト)

playwright 設定の有無を確認:

```bash
find frontend -name "playwright.config*" -o -name "e2e" -type d 2>/dev/null
```

もし無ければ手動テスト手順を README に書く:

1. TOP で「📹 参考動画から作成」CTA を押下
2. Stage 0 page に遷移
3. cost gate モーダルで confirm
4. save phase 完了 → 1.5 秒で Stage 1 page に自動遷移
5. Stage 1 page で screenplay が編集可能

#### B.4 Acceptance criteria

1. `/project/<TS>/analyze` route が機能する
2. Stage 0 page で `AnalyzeJobView` が `projectTs` prop 付きで表示される
3. analyze 完了 (= `completed` SSE event) 後 1500ms で `/project/<TS>/script` に自動遷移する
4. analyze 失敗時に FailedActions (retry / 削除 / TOP) が表示される
5. ProjectShell が Stage 0 中の project (= analyze_status pending/running/failed) を `/project/<TS>/analyze` に redirect する
6. `screenplay_name=null` の project が `(分析中)` 表示で正しく描画される
7. 既存の standalone AnalyzeJobView (= projectTs=null) は従来通り「プロジェクト作成」ボタンを表示する (= Phase D で notice 追加、Phase E で削除)

---

### Phase C: TOP UI 改修 (= ProjectList.tsx)

#### C.1 変更ファイル一覧

- `frontend/src/components/ProjectList.tsx`: 主動作 CTA 追加 + 既存ドロップダウンを副動作セクションに移動
- `frontend/src/components/ProjectCard.tsx` (= ProjectList 内 inline component の抽出): Stage 0 中のバッジ表示

#### C.2 関数単位の変更

##### C.2.1 `ProjectList.tsx` 構造改修

`/Users/hirotaka/Projects/short_movie_generator/frontend/src/components/ProjectList.tsx:154-228` の return ブロックを再構成:

```tsx
return (
  <div className="mx-auto max-w-7xl p-8">
    <header className="mb-8 flex items-start justify-between">
      <div>
        <h1 className="mb-2 text-3xl font-bold">short movie generator</h1>
        <p className="text-sm text-slate-400">
          段階的ゲート方式で動画を生成。各stageで人間が確認・承認してから次に進めます。
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Link
          to="/intent-catalog"
          className="btn-ghost whitespace-nowrap text-sm"
          title="clip_library entry の承認 / blacklist + part_registry の閲覧"
        >
          🗂 Intent Catalog →
        </Link>
      </div>
    </header>

    {error && (
      <div className="mb-4 rounded border border-rose-700 bg-rose-900/40 p-3 text-sm">
        {error}
      </div>
    )}

    {/* 主動作: 参考動画から作成 (= Phase C で追加) */}
    <CreateFromReferenceVideoSection
      onSuccess={(ts) => navigate(`/project/${ts}/analyze`)}
    />

    {/* 副動作: 既存 template から作成 (= 折りたたみ) */}
    <details className="card mb-8">
      <summary className="cursor-pointer text-sm text-slate-400 hover:text-slate-200">
        既存 template から作成 (= 量産・再利用ユーザー向け)
      </summary>
      <div className="mt-3 flex items-center gap-3">
        <select
          className="input flex-1"
          value={selectedScreenplay}
          onChange={(e) => setSelectedScreenplay(e.target.value)}
        >
          {screenplays.length === 0 && (
            <option value="">台本がありません</option>
          )}
          {screenplays.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button
          className="btn-secondary"
          disabled={!selectedScreenplay || creating}
          onClick={onCreate}
        >
          {creating ? "作成中..." : "プロジェクト作成"}
        </button>
      </div>
    </details>

    {/* 既存プロジェクト一覧 */}
    <section>{/* ...existing list rendering... */}</section>
  </div>
);
```

##### C.2.2 新 component `CreateFromReferenceVideoSection`

`ProjectList.tsx` に追加 or `frontend/src/components/CreateFromReferenceVideoSection.tsx` に切り出す。前者の方がスコープが小さく Phase C の独立性が高い:

```tsx
function CreateFromReferenceVideoSection({
  onSuccess,
}: {
  onSuccess: (ts: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [instructions, setInstructions] = useState("");
  const [fps, setFps] = useState(2.0);
  const [busy, setBusy] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const [err, setErr] = useState<string | null>(null);

  const ALLOWED_EXTS = [".mov", ".mp4", ".webm", ".mkv"];

  const onSubmit = async () => {
    if (!file) {
      setErr("動画を選択してください");
      return;
    }
    setBusy(true);
    setErr(null);
    setUploadPct(0);
    try {
      const r = await api.createProjectFromReferenceVideo(
        file,
        { instructions: instructions || undefined, fps },
        (p) => setUploadPct(p),
      );
      onSuccess(r.ts);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card mb-8 border-2 border-emerald-600/40">
      <h2 className="mb-3 text-lg font-semibold">📹 参考動画から作成</h2>
      <p className="text-xs text-slate-400 mb-4">
        参考動画をアップロードすると、Claude Vision で台本を自動生成し、
        新規プロジェクトを作成します。コスト確認モーダルが出るまで課金は発生しません。
      </p>

      <div className="space-y-3">
        <input
          type="file"
          accept={ALLOWED_EXTS.join(",")}
          disabled={busy}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm"
        />
        {busy && uploadPct < 1 && (
          <div className="h-2 w-full rounded bg-slate-700 overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${Math.round(uploadPct * 100)}%` }}
            />
          </div>
        )}
        <textarea
          rows={2}
          placeholder="追加指示 (任意): 例: TikTok UI は無視"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          className="input w-full"
          disabled={busy}
        />
        <details className="text-xs text-slate-400">
          <summary className="cursor-pointer">高度な設定</summary>
          <label className="mt-2 flex items-center gap-2">
            フレーム抽出 fps:
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="5.0"
              value={fps}
              onChange={(e) => setFps(parseFloat(e.target.value) || 2.0)}
              className="input w-20"
              disabled={busy}
            />
          </label>
        </details>
        {err && (
          <div className="text-sm text-rose-300 whitespace-pre-wrap">{err}</div>
        )}
        <button
          className="btn-primary w-full"
          disabled={!file || busy}
          onClick={onSubmit}
        >
          {busy ? "作成中..." : "📹 作成して分析を開始"}
        </button>
      </div>
    </section>
  );
}
```

##### C.2.3 `ProjectCard` で Stage 0 バッジ追加

設計 §7.6 で「TOP の既存プロジェクト一覧に Stage 0 中の project が出る → state バッジで「📹 analyze 中」を表示」とある。`ProjectList.tsx:28-111` の `ProjectCard` を修正:

```tsx
function ProjectCard({ p }: { p: ProjectListItem }) {
  const stageLabel = p.current_stage
    ? (STAGE_LABELS[p.current_stage] ?? p.current_stage)
    : "完了";
  const isDone = !p.current_stage;
  const isAnalyzing = p.analyze_status === "running" || p.analyze_status === "pending";
  const analyzeFailed = p.analyze_status === "failed";

  // Stage 0 中の project は /project/<TS>/analyze へ、それ以外は /project/<TS> へ
  const linkTo = isAnalyzing || analyzeFailed
    ? `/project/${p.timestamp}/analyze`
    : `/project/${p.timestamp}`;

  return (
    <Link to={linkTo} ...>
      <div className="relative aspect-[9/16] overflow-hidden bg-slate-900">
        {/* ...thumbnail... */}
        <div className="absolute left-2 top-2">
          {isAnalyzing ? (
            <span className="badge bg-amber-600/90 text-white">
              📹 分析中
            </span>
          ) : analyzeFailed ? (
            <span className="badge bg-rose-600/90 text-white">
              ⚠ 分析失敗
            </span>
          ) : (
            <span className={"badge " + (isDone
              ? "bg-emerald-600/90 text-white"
              : "bg-slate-900/80 text-slate-100 backdrop-blur")}>
              {isDone ? "✓ " : ""}
              {stageLabel}
            </span>
          )}
        </div>
        {/* ... */}
      </div>
      {/* ...title section... */}
    </Link>
  );
}
```

display_title が null の場合 (= Stage 0 中で caption もまだ無い) は `(分析中)` などを表示する fallback も `_project_display_title` に既に組み込まれているため、特別扱い不要。

#### C.3 テスト方針

`frontend/src/components/ProjectList.test.tsx` 新規 (もし存在しなければ):

- `CreateFromReferenceVideoSection` で動画を選択 + 「作成」を押下 → `api.createProjectFromReferenceVideo` が呼ばれ、`onSuccess(ts)` が呼ばれる
- 既存ドロップダウン UI が `<details>` の中に格納されている (= 折りたたみ)
- ProjectCard で `analyze_status="running"` のプロジェクトに「📹 分析中」バッジが付く
- ProjectCard で `analyze_status="failed"` のプロジェクトに「⚠ 分析失敗」バッジが付く + `/project/<TS>/analyze` へのリンク

#### C.4 Acceptance criteria

1. TOP page に「📹 参考動画から作成」CTA が primary (= 大きく目立つ) で表示される
2. CTA からファイル選択 + 「作成」だけで `/project/<TS>/analyze` に遷移する
3. 既存ドロップダウンは `<details>` (折りたたみ) 内の secondary action として残る
4. 既存プロジェクト一覧で Stage 0 中の project に「📹 分析中」バッジが付き、クリックで Stage 0 page に飛ぶ
5. analyze 失敗 project に「⚠ 分析失敗」バッジが付く

---

### Phase D: 旧経路 deprecation notice

#### D.1 変更ファイル一覧

- `frontend/src/pages/AnalyzePage.tsx`: 上部に deprecation banner 追加
- `frontend/src/components/AnalyzeJobView.tsx`: standalone モード時の完了モーダルにも deprecation hint 追加 (= 「Stage 0 経路に移行中」)

#### D.2 関数単位の変更

##### D.2.1 `AnalyzePage.tsx` 上部 banner

`/Users/hirotaka/Projects/short_movie_generator/frontend/src/pages/AnalyzePage.tsx:115-125` の header の直下に追加:

```tsx
<header className="flex items-center justify-between">
  <h1 className="text-xl font-semibold">参考動画から台本を生成</h1>
  <Link to="/" className="btn-ghost text-sm">
    プロジェクト一覧へ
  </Link>
</header>;

{
  /* NEW: Phase D deprecation banner */
}
<div className="card border border-amber-500/40 bg-amber-900/20">
  <div className="text-sm text-amber-200">
    <strong>📢 ご案内: </strong>
    この経路は <strong>「Stage 0 として project に統合」</strong> される
    予定です (= 今後数週間で削除)。
    <br />
    新規プロジェクトは
    <Link to="/" className="underline mx-1">
      TOP の「📹 参考動画から作成」
    </Link>
    から作成してください (= 1 操作で完結)。
    <br />
    既存の auto_*.json template を再利用したい場合は
    <Link to="/" className="underline mx-1">
      TOP の「既存 template から作成」
    </Link>
    をご利用ください。
  </div>
</div>;
```

##### D.2.2 `AnalyzeJobView.tsx` standalone モード完了時の hint

line 696 の「後で (プロジェクト一覧へ)」リンクの直下に追加 (= projectTs=null モードの分岐内):

```tsx
<div className="mt-2 text-xs text-amber-300">
  ※ 今後は TOP「📹 参考動画から作成」経由で 1 操作で完結します (= analyze +
  project 作成を分けず、Stage 0 として統合予定)。
</div>
```

#### D.3 テスト方針

- `frontend/src/pages/AnalyzePage.test.tsx`: deprecation banner が render される
- `AnalyzeJobView` の standalone モードで完了時に amber notice が render される

#### D.4 Acceptance criteria

1. `/analyze` page を開くと deprecation banner が表示される
2. AnalyzeJobView の standalone モードでも完了時に deprecation hint が表示される
3. **既存機能はそのまま動く** (= banner は情報提示のみ、機能制限なし)

---

### Phase E: 旧経路の完全削除

#### E.1 変更ファイル一覧

- `frontend/src/App.tsx`: `/analyze` route 削除 + `AnalyzePage` import 削除
- `frontend/src/pages/AnalyzePage.tsx`: ファイル削除
- `frontend/src/components/AnalyzeJobView.tsx`: standalone モード分岐 (= `projectTs=null`) 削除、`projectTs` を必須化
- `frontend/src/api.ts`: `createAnalyzeJob` (= `POST /api/screenplay/analyze`) を削除 **しない** (= `createProjectFromReferenceVideo` の内部依存として backend で残る + auto_loop CLI が使う)
- `preview_server.py`: `POST /api/screenplay/analyze` の handler を削除 (= **未削除**: auto_loop が使う場合は残す。要確認)
- `frontend/src/components/ProjectList.tsx`: header の `/analyze` Link を削除 (= 既に Phase C で削除済)
- `tests/test_preview_server_analyze.py`: 部分削除 (= 旧 endpoint 削除に追従)

#### E.2 関数単位の変更

##### E.2.1 `App.tsx`

```tsx
// 削除
// import AnalyzePage from "./pages/AnalyzePage";
// <Route path="/analyze" element={<AnalyzePage />} />
```

##### E.2.2 `AnalyzeJobView.tsx`

`Props.projectTs` を必須化 (`projectTs: string` で `?` を外す)、standalone モードの分岐ブロック (= line 671-700 全体) を削除。`AutoNavigateOnComplete` のみが完了時に呼ばれる。

##### E.2.3 backend `POST /api/screenplay/analyze` の扱い

設計 §3.2 では「✅ 残す (= 内部利用)、external trigger は段階廃止予定」。 **Phase E 時点で最終判断**:

- `auto_loop.py` (= cron / 自動量産経路) が `analyze.run()` (= module 直接呼び) を使っているので、**HTTP endpoint は削除しても auto_loop は影響なし**
- `frontend/src/api.ts::createAnalyzeJob` は `/analyze` page (= AnalyzePage) からしか使われていない → **AnalyzePage 削除 = createAnalyzeJob 削除可能**
- 仮に CI / 外部スクリプトから叩かれていないかを Phase E 直前に grep 監査:
  ```bash
  grep -rn "createAnalyzeJob\|/api/screenplay/analyze" frontend/ scripts/ tools/ ops/
  ```
- 残ってなければ削除。残っていれば残す (= Phase E+1 で個別対応)

##### E.2.4 旧テストの整理

`tests/test_preview_server_analyze.py` の standalone POST `/api/screenplay/analyze` 経路に依存するテストを削除 or skip:

- 削除候補: `test_create_analyze_job_with_uploaded_video`, `test_create_job_rejects_unknown_video`, `test_create_job_rejects_invalid_sha`, `test_create_job_filters_unknown_options`
- 保持: `test_get_job_includes_phases`, `test_confirm_rejects_when_not_awaiting`, `test_cancel_*` (= 既存 endpoint で job ID 経由のもの、Phase A の新エンドポイント経由でも有効)

代替テストは Phase A の新ファイル `tests/test_routes_projects_from_reference_video.py` で網羅済み。

#### E.3 テスト方針

- 削除対象テストの代替が `tests/test_routes_projects_from_reference_video.py` で揃っていることを確認
- `pytest tests/test_routes_projects_from_reference_video.py tests/test_preview_server_analyze.py` で全 pass

#### E.4 Acceptance criteria

1. `/analyze` route が 404 (= 旧 page 削除)
2. AnalyzeJobView の `projectTs` が必須化
3. backend `POST /api/screenplay/analyze` が削除済 (or 内部用としてのみ残る = Phase A 内部使用継続)
4. 既存 backend テストが全 pass
5. **設計 §9 受け入れ基準 1〜6 を全て満たす** (= 設計書の最終目標達成)

---

## C. テスト方針 (= 全体)

### C.1 backend (pytest)

#### unit test レベル

- `tests/test_progress_store.py` (新規 or 拡張): `mark_analyze_started` / `mark_analyze_completed` / `mark_analyze_failed` / `analyze_status`
- `tests/test_staged_pipeline.py` (拡張): `init_pending_metadata` / `update_metadata_after_analyze` / nullable `write_metadata`
- `tests/test_analyze_runner_save_hook.py` (新規): `_PhaseTracker._on_save_complete` の挙動 (project_ts あり / なし / hook 失敗)
- `tests/test_routes_helpers.py` (拡張): `is_analyze_pending`

#### integration test レベル

- `tests/test_routes_projects_from_reference_video.py` (新規):
  - 新 endpoint POST 成功 → 201 + ts + analyze_job_id
  - metadata.json 初期化が正しい (`screenplay_name=null`, `analyze_job_id=<id>`, `created_at=<iso>`)
  - progress.json 初期化が正しい (`stages.analyze.status="running"`)
  - reference_video upload + dedup
  - 不正 ext / file 無し → 400
  - analyze runner.start が mock で呼ばれた (= `monkeypatch.setattr(analyze_runner, "start", lambda jid: started.append(jid))`)
  - save phase hook 完了後の状態 (= `_PhaseTracker._on_save_complete` を直接呼んで模擬)

- `tests/test_routes_projects_from_reference_video_full_cycle.py` (新規、長い integration test):
  - 新 endpoint で project 作成
  - mock `analyze.pipeline.run` で screenplay を返す runner stub を仕込む
  - runner thread を実際に走らせる (= sleep poll で wait)
  - 完了後に `temp/<TS>/screenplay.json` snapshot + metadata.json + progress.json を全部検証

### C.2 frontend (vitest)

- 既存パターン (= `frontend/src/**.test.ts*`) で:
  - `api.test.ts` の `createProjectFromReferenceVideo` テスト
  - `AnalyzeJobView.test.tsx` の `projectTs` prop による分岐
  - `AnalyzeStage0Page.test.tsx` の analyze_status による表示分岐
  - `ProjectList.test.tsx` の `CreateFromReferenceVideoSection` 動作 + Stage 0 バッジ

### C.3 e2e (playwright)

playwright 設定の有無を確認する作業を Phase A の最初に実施:

```bash
find frontend -name "playwright*" -type f 2>/dev/null
ls frontend/e2e 2>/dev/null
```

無ければ手動 e2e 手順を `docs/plannings/2026-05-10_analyze-project-handoff-implementation.md` の §C.3 に書く:

1. `npm run dev` で frontend + `python preview_server.py` で backend 起動
2. ブラウザで `/` を開く
3. 「📹 参考動画から作成」で動画を 1 個アップロード
4. `/project/<TS>/analyze` に遷移、進捗 SSE が見える
5. cost gate モーダルで confirm
6. save phase 完了 → 1.5 秒で `/project/<TS>/script` に自動遷移
7. Stage 1 で screenplay 編集可能 + 保存可能
8. Stage 2 (TTS) 以降が通常通り進行

### C.4 analyze pipeline cache の確認

設計 §9 受け入れ基準 6: 「既存の analyze cache (= content-addressed frames / audio) が壊れていないこと」

- `tests/test_analyze_cache.py` (= 既存) を全 pass
- 同一動画を Phase A 経路で 2 回 POST して、2 回目は frames / audio / whisper / acoustic phases が `from_cache=True` を返すことを SSE event で確認 (= Phase A 統合 test に含める)

### C.5 analyze 失敗時の retry / 削除フロー

- `tests/test_routes_projects_retry_analyze.py` (新規): retry endpoint で新 analyze_job_id が再 enqueue される、metadata.analyze_job_id が更新される、progress.stages.analyze が再 running 状態になる
- `tests/test_routes_projects_delete.py` (新規): delete endpoint で `temp/<TS>/` ディレクトリが消える、analyze_jobs から DELETE される (or status="cancelled" になる)、reference_video は dedup なので消さない

---

## D. リスクと未解決事項の解像度上げ

### D.1 §7.1 analyze 失敗時の project 残し方 (= 候補 2 推奨)

#### 推奨: project を残しつつ retry / 削除を可能にする

**新エンドポイント (Phase A に含める)**:

```python
# routes/projects.py に追加

@projects_bp.route("/api/projects/<ts>/retry-analyze", methods=["POST"])
def api_retry_analyze(ts):
    """Stage 0 (analyze) を再起動する。

    - 既存の analyze_job (= failed / cancelled) は保持 (= 課金履歴のため)
    - 新しい analyze_job を作成して project に紐付け
    - metadata.analyze_job_id を新 ID に更新
    - progress.stages.analyze を running に戻す

    制約: 既存の analyze_status が "failed" or "cancelled" のときのみ許可
    (= "running" 中の二重起動を防ぐ)。
    """
    from analyze import job as analyze_job
    from analyze import runner as analyze_runner

    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({
            "error_code": "ANALYZE_PROJECT_NOT_FOUND",
            "message": "プロジェクトが存在しません",
        }), 404

    meta = staged_pipeline.read_metadata(project_path) or {}
    old_job_id = meta.get("analyze_job_id")
    if not old_job_id:
        return jsonify({
            "error_code": "ANALYZE_JOB_ID_MISSING",
            "message": "このプロジェクトに analyze_job_id がありません",
        }), 400

    status = progress_store.analyze_status(project_path)
    if status not in ("failed", None):
        return jsonify({
            "error_code": "ANALYZE_NOT_RETRYABLE",
            "message": f"current status={status}: failed のときのみ retry 可",
        }), 409

    # 既存 job から video_sha256 と options を取得
    try:
        old_job = analyze_job.get_job(old_job_id)
    except KeyError:
        return jsonify({
            "error_code": "ANALYZE_JOB_NOT_FOUND",
            "message": f"old job not found: {old_job_id}",
        }), 404

    # 新ジョブ作成 (= cache hit するので追加課金は最小)
    new_job = analyze_job.create_job(
        old_job.video_sha256, old_job.options, project_ts=ts,
    )

    # metadata 更新
    meta["analyze_job_id"] = new_job.id
    if "analyze_hook_error" in meta:
        del meta["analyze_hook_error"]
    io_utils.atomic_write_json(
        os.path.join(project_path, "metadata.json"), meta,
    )

    # progress.json 更新
    progress_store.mark_analyze_started(project_path)

    # runner 起動
    analyze_runner.start(new_job.id)

    return jsonify({"ok": True, "new_analyze_job_id": new_job.id}), 200


@projects_bp.route("/api/projects/<ts>", methods=["DELETE"])
def api_delete_project(ts):
    """project ディレクトリと関連 analyze_job を削除する。

    - temp/<TS>/ ディレクトリ全体を削除
    - 紐付いている analyze_job が running 中ならキャンセル要求してから削除
    - reference_videos は dedup 済みなので **消さない** (= 他の project が
      参照している可能性がある)

    注意: Stage 1+ (= 既に screenplay snapshot がある) project でも
    同じ動作。既存仕様だと削除エンドポイント自体が存在しないので、Phase A
    の追加でこのエンドポイント自体が新設。
    """
    from analyze import job as analyze_job
    from analyze import runner as analyze_runner
    import shutil

    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({
            "error_code": "ANALYZE_PROJECT_NOT_FOUND",
            "message": "プロジェクトが存在しません",
        }), 404

    meta = staged_pipeline.read_metadata(project_path) or {}
    job_id = meta.get("analyze_job_id")
    if job_id:
        try:
            j = analyze_job.get_job(job_id)
            if j.status in ("running", "pending", "dryrunning", "awaiting_confirm"):
                analyze_runner.cancel(job_id)
        except KeyError:
            pass

    # ディレクトリ削除
    try:
        shutil.rmtree(project_path)
    except OSError as e:
        return jsonify({
            "error_code": "PROJECT_DELETE_FAILED",
            "message": f"directory delete failed: {e}",
        }), 500

    return jsonify({"ts": ts, "deleted": True}), 200
```

frontend `api.ts` 追加:

```typescript
retryAnalyzeForProject: (ts: string) =>
  http<{ ok: true; new_analyze_job_id: string }>(
    `/api/projects/${ts}/retry-analyze`,
    { method: "POST" },
  ),
deleteProject: (ts: string) =>
  http<{ ts: string; deleted: true }>(
    `/api/projects/${ts}`,
    { method: "DELETE" },
  ),
```

### D.2 §7.2 analyze 中の他操作の disable 範囲

#### 実装方針

- **Stage 0 中の同 project の Stage 1+ stage runner は backend で reject** (= 403 ANALYZE_STAGE_NOT_READY):
  - `routes/stages.py::api_run_next` (line 153) と `api_regen` (line 170) の冒頭で `is_analyze_pending(ts)` を呼び、True なら 403 を返す
  - `routes/projects.py::api_put_project_abstract` (= preview_server.py:891) も同様

- **frontend では ProjectShell が `analyze_status="running"` の場合に Stage 0 page に redirect** (= Phase B.2.6) しているので、UI からはそもそも Stage 1+ にアクセスできない

- **並行で他の project の Stage 1+ は許可** (= job_runner の `_active_ts` は per-ts なので影響なし)

具体実装:

```python
# routes/_helpers.py に追加 (= is_analyze_pending の隣)

def assert_analyze_completed(ts: str, *, temp_dir: str | None = None) -> None:
    """Stage 0 が completed でなければ 403 abort する。

    Stage 1+ stage runner / Stage 1 編集 endpoint で呼ぶ。
    """
    from flask import abort
    from werkzeug.exceptions import HTTPException
    if is_analyze_pending(ts, temp_dir=temp_dir):
        # abort(403, ...) は werkzeug の HTML を返すので、JSON で返す
        from flask import jsonify
        response = jsonify({
            "error_code": "ANALYZE_STAGE_NOT_READY",
            "message": "Stage 0 (analyze) が完了するまで操作できません",
        })
        response.status_code = 403
        # Flask の except HTTPException で捕捉される形で raise
        raise HTTPException(response=response)
```

### D.3 §7.5 metadata.screenplay_name=null grep 監査結果

→ **§A.1 の表に集約済み**。要約:

- 修正必須: `staged_pipeline.write_metadata`, `routes/projects.py::api_project_detail`, `routes/_helpers.py::load_screenplay_for_project` 周辺、`frontend/src/types.ts`, `ProjectShell.tsx`
- defensive 化済 (= 既に nullable 対応): `routes/projects.py::_project_display_title`, `routes/_helpers.py:160` の or 連鎖, `final_import/publish.py:553`, `scripts/migrate_to_project_snapshot.py`
- 影響なし: `screenplay_validator.py`, `scripts/dashboard.py` (= analytics DB 経由), `scripts/ingest_screenplay.py` (= argv 直接), `auto_loop.py` (= template 経由)

### D.4 §7.6 Stage 0 中 project の project list 表示

→ **§B.2.7 (ProjectCard 修正) と §A.2.9 (api_projects レスポンス拡張) で実装**。要約:

- backend: `analyze_status` を response に含める
- frontend: ProjectCard で `analyze_status="running"` → 「📹 分析中」バッジ + `/project/<TS>/analyze` へのリンク
- frontend: ProjectCard で `analyze_status="failed"` → 「⚠ 分析失敗」バッジ
- 一覧 sort は `created_at` 降順そのまま (= `api_projects` の `sorted(..., reverse=True)` 既存)

---

## E. PR 構成と commit 粒度

### E.1 ブランチ構成

すべての PR は `main` をベースとする (= 設計 §6 通り)。各 PR は独立して merge 可能。

```
main
 ├── analyze-project-handoff/phase-a-backend
 ├── analyze-project-handoff/phase-b-frontend
 ├── analyze-project-handoff/phase-c-top-ui
 ├── analyze-project-handoff/phase-d-deprecation-notice
 └── analyze-project-handoff/phase-e-removal (= main + Phase A〜D merge 後)
```

Phase A〜D は **並行に開発可能** (= 互いに依存しない設計)、ただし:

- Phase B は **Phase A の API spec が確定していれば** UI 開発可能 (= mock fetch で進められる)
- Phase C は Phase B の `createProjectFromReferenceVideo` API method を使うので、Phase B の api.ts 変更を先に merge すると C が楽
- Phase D は Phase A〜C 完了後、運用 1〜2 日待って notice 表示 (= ユーザーが新経路を体験)
- Phase E は Phase D 公開後 1 週間 (= 設計 §6 目安)

### E.2 PR 内の commit 粒度

#### Phase A backend

7 commit を推奨:

1. `add: progress_store.STAGES に "analyze" 追加 + helper 関数群` (= mark_analyze_started/completed/failed/analyze_status)
2. `change: analyze_jobs schema に project_ts 列追加 (= migration 込み)`
3. `change: staged_pipeline.write_metadata を nullable 対応 + init_pending_metadata / update_metadata_after_analyze 追加`
4. `add: analyze.runner._PhaseTracker._on_save_complete hook (= save phase 完了で project metadata + Stage 1 unlock)`
5. `add: POST /api/projects/from-reference-video エンドポイント`
6. `add: POST /api/projects/<ts>/retry-analyze + DELETE /api/projects/<ts> エンドポイント`
7. `add: tests for from-reference-video / retry / delete + STAGES 追加に伴う既存 test 更新`

レビュー順序:

1. → 2. → 3. の順で読むと「データモデル変更がどう staged_pipeline に伝わるか」が分かる
2. → 5. → 6. の順で「runner hook → 新エンドポイント → retry/delete」と読める
3. は最後にまとめて読む

#### Phase B frontend

5 commit を推奨:

1. `change: types.ts の ProjectListItem / ProjectDetail を nullable 対応 + AnalyzeStageStatus 追加`
2. `add: api.ts に createProjectFromReferenceVideo / retryAnalyzeForProject / deleteProject 追加`
3. `change: AnalyzeJobView に projectTs prop 追加 + AutoNavigateOnComplete 内部 component 追加`
4. `add: AnalyzeStage0Page (= /project/<TS>/analyze route) + ProjectShell の Stage 0 redirect`
5. `add: tests for api / AnalyzeJobView / AnalyzeStage0Page`

#### Phase C TOP UI

3 commit を推奨:

1. `add: CreateFromReferenceVideoSection component`
2. `change: ProjectList header / 主動作セクション再構成 + ProjectCard に Stage 0 バッジ追加`
3. `add: tests for ProjectList`

#### Phase D deprecation notice

2 commit を推奨:

1. `add: AnalyzePage / AnalyzeJobView standalone モードに deprecation banner / hint 追加`
2. `add: tests for deprecation banner`

#### Phase E 削除

3 commit を推奨:

1. `delete: AnalyzePage + /analyze route + AnalyzeJobView standalone モード分岐`
2. `delete: backend POST /api/screenplay/analyze (= 内部利用継続なら delete せず docstring 更新)`
3. `delete: 旧経路 test の整理 + remove obsolete fixture`

### E.3 レビューしやすい順序

各 PR で:

1. **設計ドキュメントの該当 phase へのリンク** を PR description 冒頭に貼る (`docs/plannings/2026-05-10_analyze-project-handoff.md#phase-a` など)
2. **scope** を 1 行で書く (例: 「Phase A scope: backend のみ。frontend は触らない。」)
3. **before / after の手動動作確認手順** を明記 (= 動画 1 つで十分)
4. **screenshot / SSE event log** を貼る (= Phase B 以降)

### E.4 デプロイ順序

設計 §6 通り:

- Phase A merge → 即 staging deploy → smoke test (= curl で新エンドポイント叩く)
- Phase B merge → frontend build → staging で動作確認
- Phase C merge → 主動作 CTA を staging で押下確認
- Phase D merge → 1 週間運用、deprecation banner で旧経路使用率を観測
- Phase E merge → 旧経路完全削除、backend 旧 endpoint も grep で外部依存を再確認してから削除

---

## F. 追加メモ: Phase A 実装時に注意すべき細部

### F.1 reference_video upload ロジックの共通化

§B.2.8 の `api_create_project_from_reference_video` 実装中で「preview_server.api_upload_reference_video のロジックをコピペで実装する。Phase E の旧経路削除時に共通化」と書いた。これは **設計 §3.2 で「`POST /api/reference_videos` を残す」と決めている** ので、Phase A 時点では:

- 共通 helper を `routes/_helpers.py::save_reference_video(file: FileStorage) -> tuple[str, dict]` (= sha, metadata) として抽出
- `POST /api/reference_videos` (preview_server.py:506) と `POST /api/projects/from-reference-video` の両方が呼ぶ
- これにより「Phase E で旧 endpoint を消すとロジック重複が消える」問題が起こらない (= Phase E (#182) で旧 POST /api/screenplay/analyze を削除した際、helper 共通化済みでロジック重複は実際に発生しなかった)

具体的な抽出関数:

```python
# routes/_helpers.py に追加

def save_reference_video(
    file_storage,
) -> tuple[str, dict]:
    """multipart の reference video を dedup + sha256 ベースで保存する。

    Returns: (sha256, metadata dict)
    Raises: ValueError on invalid extension / file
    """
    from analyze import job as analyze_job
    from analyze.cache import file_sha256
    import uuid

    name = file_storage.filename or "video"
    ext = os.path.splitext(name)[1].lower()
    if ext not in analyze_job.ALLOWED_VIDEO_EXTS:
        raise ValueError(
            f"unsupported extension: {ext}. "
            f"allowed: {list(analyze_job.ALLOWED_VIDEO_EXTS)}"
        )

    ref_dir = analyze_job.reference_videos_dir()
    tmp = ref_dir / f".tmp_{uuid.uuid4().hex}{ext}"
    try:
        file_storage.save(str(tmp))
        sha = file_sha256(str(tmp))
        size = os.path.getsize(tmp)
        existing = analyze_job.get_reference_video(sha)
        if existing:
            tmp.unlink(missing_ok=True)
            analyze_job.touch_reference_video(sha)
            return sha, {**existing, "deduplicated": True}
        final_path = ref_dir / f"{sha}{ext}"
        tmp.replace(final_path)
        # _ffprobe_duration は preview_server で定義されているが、
        # 同様に routes/_helpers.py に抽出するか、analyze.cache.py に置く
        from preview_server import _ffprobe_duration
        duration = _ffprobe_duration(str(final_path))
        analyze_job.upsert_reference_video(
            sha, original_name=os.path.basename(name),
            size_bytes=size, duration_sec=duration,
        )
        return sha, {
            "sha256": sha, "size_bytes": size,
            "duration_sec": duration,
            "original_name": os.path.basename(name),
            "deduplicated": False,
        }
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
```

### F.2 progress_store STAGES に "analyze" 追加の副作用

`progress_store.next_stage()` (line 88-97) は「最初の generated_at が None の stage」を返す。`"analyze"` を STAGES の先頭に追加すると:

- 既存 project (= analyze 経由ではない、template 経由) は `progress.stages.analyze.generated_at = None` のまま
- → `next_stage()` が `"analyze"` を返す (= 今までは `"script"` を返していた)
- → `routes/stages.py::api_run_next` が `progress_store.next_stage(project_path)` で取得した stage を `STAGE_RUNNERS[stage]` で実行しようとして KeyError

**対応**: `staged_pipeline.STAGE_RUNNERS` に `"analyze"` が無いので、`run_next_stage` (line 511) の最初で:

```python
def run_next_stage(screenplay, screenplay_name, ts_path) -> str | None:
    nxt = progress_store.next_stage(ts_path)
    if nxt is None:
        return None
    if nxt == "analyze":
        # Stage 0 は HTTP endpoint (POST /api/projects/from-reference-video)
        # 経由でしか起動しない。CLI からは template 経由で project を作るので、
        # ここに到達したら "Stage 0 を skip して script に進める" 扱いにする。
        # (= 既存 template 経由 project が新 STAGES 順序の影響を受けないため)
        progress_store.mark_analyze_completed(ts_path)
        nxt = progress_store.next_stage(ts_path)
        if nxt is None:
            return None
    if nxt in progress_store.EXTERNAL_ACTION_STAGES:
        return None
    # ...既存コード...
```

これで `auto_loop.py::_create_project` (= staged_pipeline.run_script を直接呼ぶ) も影響なし (= run_script で `progress_store.mark_generated(ts_path, "script")` するので `next_stage` は `tts` を返す)。

### F.3 `auto_loop.py` の影響

`auto_loop.py::_create_project` (line 135-143) は `staged_pipeline.run_script` を直接呼ぶので Phase A の新 endpoint 経路を使わない。**変更不要**。

ただし、auto_loop で作られた project は `progress.stages.analyze.generated_at = None` のまま。これは `next_stage()` の挙動に影響するので **F.2 の対応** が必要。

### F.4 `frontend/src/components/ProjectShell.tsx` の loadProgress polling

ProjectShell は `api.progress(ts)` を polling していると思われる。Stage 0 中の polling は:

- analyze_status="completed" になったら redirect to script (= ProjectShell の Stage 1 page)
- analyze_status="failed" になったら redirect to /project/<TS>/analyze (= Stage 0 page で FailedActions 表示)

ProjectShell が既に polling している progress に `stages.analyze` が追加されるので、ロジックは:

```tsx
useEffect(() => {
  const interval = setInterval(async () => {
    const r = await api.progress(ts);
    setProgress(r.progress);
    // NEW: Stage 0 状態の変化を検出
    const analyzeStatus = r.progress.stages?.analyze?.status;
    if (
      analyzeStatus === "completed" &&
      location.pathname.endsWith("/analyze")
    ) {
      navigate(`/project/${ts}/script`, { replace: true });
    }
  }, 5000);
  return () => clearInterval(interval);
}, [ts]);
```

ただし ProjectShell は Stage 0 page (= `/project/<TS>/analyze`) では表示されない (= Phase B.2.4 で Stage 0 を独立 route にしたため)。なので **AnalyzeStage0Page で polling**:

```tsx
// AnalyzeStage0Page.tsx の useEffect 追加
useEffect(() => {
  if (!ts) return;
  const interval = setInterval(async () => {
    try {
      const r = await api.project(ts);
      setDetail(r);
      if (r.analyze_status === "completed") {
        navigate(`/project/${ts}/script`, { replace: true });
      }
    } catch {}
  }, 5000);
  return () => clearInterval(interval);
}, [ts]);
```

ただし `AnalyzeJobView` は SSE で event を受信して即座に画面更新するので、polling は **fallback** (= SSE が切れた場合の安全網) 役割。

### F.5 既存 "Phase A (analyze_job_id 永続化対応) より前に作成された project" の扱い

`scripts/backfill_analyze_job_id.py` (= 既存) は既に metadata に `analyze_job_id` を後付けする migration 用 script。Phase A の新 metadata schema 変更 (= `screenplay_name` nullable + `progress.stages.analyze` 追加) 後でも:

- 既存 project: `screenplay_name=str` のまま、`progress.stages.analyze.generated_at=null` で出現
- F.2 の対応で `next_stage` が `analyze` を返した場合に skip → script に進む

→ 既存 project は **migration 不要**。新規 project だけが Phase A 経路の挙動になる。

---

## G. 想定される追加課題と次フェーズ予告

このドキュメントの範囲外だが、Phase A〜E 実装後に検討:

1. **Stage 0 page で `awaiting_confirm` のコスト確認モーダルを別 UI として強調**: 現状 AnalyzeJobView 内の `<div className="card border border-amber-500/40">` だが、Stage 0 page では「最も重要な操作」なのでモーダル化検討
2. **Stage 0 progress が SSE 切断時に止まる問題**: `EventSource.onerror` で再接続 + 状態 fetch
3. **複数 project 作成のキューイング UI**: `_MAX_CONCURRENT=1` (= analyze runner) なので、TOP で複数動画を続けて upload しても 1 つずつしか走らない。「3 件待機中」のような UI 表示が欲しい
4. **template 一覧 (= `_list_screenplays`) に auto\_<sha> 以外の手動 template が混じる場合のソート**: 現在は filename alphabetical。利用頻度順 / 最新作成順への切り替え検討

---

## H. 実装中の懸念点 (= Phase A 実装時に再確認)

1. **`_PhaseTracker._on_save_complete` での `progress_store.mark_approved(ts_path, "script")` の挙動**: `mark_approved` は `generated_at` 必須 (`progress_store.py:62-65`)。`mark_generated("script")` を先に呼んでから `mark_approved("script")` の順序を守る必要 (= F.4 で記述済)。
2. **`screenplays/auto_<sha>.json` と `temp/<TS>/screenplay.json` の sha256 一致**: snapshot は `shutil.copyfile` でバイト単位コピーすれば必ず一致する。validator 経由で再 dump すると差が出る可能性 → `shutil.copyfile` 一択。
3. **`reference_videos` の duration_sec が dedup ケースで取れない問題**: 既存 entry を流用すると `existing["duration_sec"]` を read。**OK**。
4. **`progress_store.STAGES` への `"analyze"` 追加が他の test (= test_analytics_db_phase4 等) に影響するか**: grep でテスト一覧を確認してから決める。

---

## I. 関連コード参照 (= 実装着手時の必読リスト)

- `docs/plannings/2026-05-10_analyze-project-handoff.md` (= 設計、必読)
- `docs/abstract-screenplay-design.md` §1 (= analyze → snapshot のフロー全体)
- `staged_pipeline.py` line 32-50 (= template 読み出し), line 208-275 (= write_metadata + run_script), line 511-540 (= run_next_stage)
- `progress_store.py` line 1-50 (= STAGES + load/save), line 88-97 (= next_stage), line 113-149 (= reset / revoke)
- `analyze/runner.py` line 1-260 全体
- `analyze/pipeline.py` line 280-552 (= run() の save phase)
- `analyze/job.py` line 65-135 (= AnalyzeJob + create_job)
- `routes/projects.py` 全体
- `routes/_helpers.py` 全体
- `preview_server.py` line 503-608 (= reference_videos endpoints), line 760-1014 (= analyze endpoints)
- `frontend/src/api.ts` line 100-330 (= http / api object 全体)
- `frontend/src/components/AnalyzeJobView.tsx` line 670-705 (= 完了ボタン分岐)
- `frontend/src/components/ProjectList.tsx` 全体
- `frontend/src/pages/AnalyzePage.tsx` 全体
- `frontend/src/App.tsx` 全体
- `frontend/src/types.ts` line 138-160 (= ProjectListItem / ProjectDetail), line 218-300 (= analyze types)

---

### Critical Files for Implementation

- `/Users/hirotaka/Projects/short_movie_generator/routes/projects.py` (= 新エンドポイント追加 + api_projects レスポンス拡張 + api_project_detail の nullable 化、Phase A の中核)
- `/Users/hirotaka/Projects/short_movie_generator/analyze/runner.py` (= save phase 完了 hook で project metadata + Stage 1 unlock を仕掛ける、Phase A の中核)
- `/Users/hirotaka/Projects/short_movie_generator/staged_pipeline.py` (= write_metadata の nullable 対応 + init_pending_metadata / update_metadata_after_analyze の新規 helper、Phase A の中核)
- `/Users/hirotaka/Projects/short_movie_generator/progress_store.py` (= STAGES に "analyze" を追加 + Stage 0 用 helper 関数群、Phase A の中核)
- `/Users/hirotaka/Projects/short_movie_generator/frontend/src/components/AnalyzeJobView.tsx` (= projectTs prop による分岐 + AutoNavigateOnComplete 追加、Phase B の中核)
