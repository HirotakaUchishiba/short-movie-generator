import hashlib
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import config

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_DB_PATH = Path(config.BASE_DIR) / "data" / "analytics.db"
CURRENT_SCHEMA_VERSION = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db_path() -> Path:
    return Path(os.environ.get("ANALYTICS_DB_PATH", str(DEFAULT_DB_PATH)))


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        # 既存 DB の videos に final_* カラムが無い場合に追加 (additive migration)
        _ensure_column(conn, "videos", "final_imported",
                       "final_imported INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "videos", "final_filename", "final_filename TEXT")
        _ensure_column(conn, "videos", "final_audio_match_score",
                       "final_audio_match_score REAL")
        # schema v5: reference_videos に source_url / fetched_at / license_status を
        # 追加。既存 row は NULL / "unconfirmed" のまま (= UI upload 経路は影響なし)。
        _ensure_column(conn, "reference_videos", "source_url", "source_url TEXT")
        _ensure_column(conn, "reference_videos", "fetched_at", "fetched_at TEXT")
        _ensure_column(conn, "reference_videos", "license_status",
                       "license_status TEXT DEFAULT 'unconfirmed'")
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = (row["v"] or 0) if row else 0
        if current < CURRENT_SCHEMA_VERSION:
            conn.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES(?, ?)",
                (CURRENT_SCHEMA_VERSION, _now()),
            )
    logger.info("analytics DB initialized at %s", _db_path())


def _ensure_column(conn: sqlite3.Connection, table: str,
                   column: str, ddl: str) -> None:
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def upsert_screenplay(path: str) -> str:
    """screenplayファイルを読み込み、DBに登録。既存ならcontent diff時のみ更新。
    Returns: screenplay id (sha256[:12])
    """
    full_path = os.path.abspath(path)
    with open(full_path, "rb") as f:
        raw_bytes = f.read()
    sha = hashlib.sha256(raw_bytes).hexdigest()
    sp_id = sha[:12]
    raw_json = raw_bytes.decode("utf-8")
    sp = json.loads(raw_json)

    scenes = sp.get("scenes") or []
    total_duration = sum(float(s.get("duration", 0)) for s in scenes)
    line_count = sum(len(s.get("lines") or []) for s in scenes)

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM screenplays WHERE id = ?", (sp_id,)
        ).fetchone()
        if existing:
            logger.info("screenplay %s は既に登録済み", sp_id)
            return sp_id

        conn.execute(
            """INSERT INTO screenplays
               (id, path, name, sha256, created_at, raw_json, caption,
                audio_mode, scene_count, line_count, total_duration)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sp_id,
                full_path,
                os.path.basename(full_path),
                sha,
                _now(),
                raw_json,
                sp.get("caption"),
                sp.get("audio_mode"),
                len(scenes),
                line_count,
                total_duration,
            ),
        )
        logger.info("screenplay %s (%s) 登録", sp_id, os.path.basename(full_path))
    return sp_id


def update_screenplay_tags(screenplay_id: str, tags: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE screenplays
               SET hook_type = ?, tone = ?, dominant_emotion = ?,
                   theme = ?, character_archetype = ?, auto_tagged_at = ?
               WHERE id = ?""",
            (
                tags.get("hook_type"),
                tags.get("tone"),
                tags.get("dominant_emotion"),
                tags.get("theme"),
                tags.get("character_archetype"),
                _now(),
                screenplay_id,
            ),
        )


def update_video_final(video_id: str, *, output_path: str,
                       duration_sec: float | None = None,
                       final_imported: bool = False,
                       final_filename: str | None = None,
                       final_audio_match_score: float | None = None) -> bool:
    """既存 video 行の output_path / duration / final_* だけを更新する。

    `screenplay_id` / `generation_cost_usd` / `generated_at` は触らない
    (= ingest 時の値を保持)。Returns: 更新行があれば True、無ければ False。
    """
    with get_connection() as conn:
        cur = conn.execute(
            """UPDATE videos
               SET output_path = ?, duration_sec = ?,
                   final_imported = ?, final_filename = ?,
                   final_audio_match_score = ?
               WHERE id = ?""",
            (os.path.abspath(output_path), duration_sec,
             1 if final_imported else 0, final_filename,
             final_audio_match_score, video_id),
        )
        updated = cur.rowcount > 0
    if updated:
        logger.info(
            "video %s 更新 (final_imported=%s, final_filename=%s)",
            video_id, final_imported, final_filename,
        )
    return updated


def insert_video(video_id: str, screenplay_id: str, output_path: str,
                 duration_sec: float | None = None,
                 generation_cost_usd: float | None = None,
                 final_imported: bool = False,
                 final_filename: str | None = None,
                 final_audio_match_score: float | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO videos
               (id, screenplay_id, output_path, duration_sec, generation_cost_usd,
                generated_at, final_imported, final_filename,
                final_audio_match_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (video_id, screenplay_id, os.path.abspath(output_path),
             duration_sec, generation_cost_usd, _now(),
             1 if final_imported else 0, final_filename,
             final_audio_match_score),
        )
        logger.info("video %s (screenplay=%s, final_imported=%s) 登録",
                    video_id, screenplay_id, final_imported)


def register_post(video_id: str, platform: str, platform_post_id: str,
                  url: str | None = None, posted_at: str | None = None,
                  caption: str | None = None,
                  hashtags: list[str] | None = None) -> str:
    post_id = f"{platform}:{platform_post_id}"
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO posts
               (id, video_id, platform, platform_post_id, url, posted_at,
                caption, hashtags, registered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (post_id, video_id, platform, platform_post_id, url, posted_at,
             caption,
             json.dumps(hashtags, ensure_ascii=False) if hashtags else None,
             _now()),
        )
        logger.info("post %s (video=%s) 登録", post_id, video_id)
    return post_id


def insert_metrics(post_id: str, metrics: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO post_metrics
               (post_id, fetched_at, views, likes, comments, shares, saves,
                watch_time_sec, avg_view_duration, completion_rate, ctr, raw_response)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                post_id,
                _now(),
                metrics.get("views"),
                metrics.get("likes"),
                metrics.get("comments"),
                metrics.get("shares"),
                metrics.get("saves"),
                metrics.get("watch_time_sec"),
                metrics.get("avg_view_duration"),
                metrics.get("completion_rate"),
                metrics.get("ctr"),
                json.dumps(metrics.get("raw_response") or {}, ensure_ascii=False),
            ),
        )


def list_active_posts(platform: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if platform:
            rows = conn.execute(
                "SELECT * FROM posts WHERE platform = ?", (platform,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM posts").fetchall()
        return [dict(r) for r in rows]


def list_screenplays() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM screenplays ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def query_performance() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM v_performance").fetchall()
        return [dict(r) for r in rows]


# ───────────── generation_records (Phase 0: 計測基盤) ─────────────

def append_stage_run(
    *,
    ts: str,
    stage: str,
    started_at: str,
    ended_at: str | None,
    status: str,
    retry_count: int = 0,
    cost_usd: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """generation_records.stage_runs に 1 stage 実行を追記する。

    ``ts`` 行が無ければ作成する (= 各 stage の最初の append が自動で init)。
    ``total_cost_usd`` は付随する ``cost_usd`` を合算する。"""
    entry: dict[str, Any] = {
        "stage": stage,
        "started_at": started_at,
        "ended_at": ended_at,
        "status": status,
        "retry_count": retry_count,
        "cost_usd": cost_usd,
    }
    if extra:
        entry.update(extra)

    delta_cost = float(cost_usd or 0.0)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT stage_runs, total_cost_usd FROM generation_records WHERE ts = ?",
            (ts,),
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO generation_records (ts, stage_runs, total_cost_usd, created_at)
                   VALUES (?, ?, ?, ?)""",
                (ts, json.dumps([entry], ensure_ascii=False), delta_cost, _now()),
            )
        else:
            try:
                runs = json.loads(row["stage_runs"] or "[]")
                if not isinstance(runs, list):
                    runs = []
            except (json.JSONDecodeError, TypeError):
                runs = []
            runs.append(entry)
            new_total = float(row["total_cost_usd"] or 0.0) + delta_cost
            conn.execute(
                """UPDATE generation_records
                   SET stage_runs = ?, total_cost_usd = ?
                   WHERE ts = ?""",
                (json.dumps(runs, ensure_ascii=False), new_total, ts),
            )


def get_generation_record(ts: str) -> dict | None:
    """ts に対応する generation_records 行を返す。無ければ None。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM generation_records WHERE ts = ?", (ts,),
        ).fetchone()
        return dict(row) if row else None


# update_generation_record で扱うフィールド (`json.dumps` で TEXT 化する column を区別)。
_GEN_REC_JSON_FIELDS = frozenset({"prompts", "seeds", "api_meta", "validator_scores"})
_GEN_REC_PLAIN_FIELDS = frozenset({
    "video_id", "reference_video_id", "screenplay_sha", "status",
})


def update_generation_record(ts: str, **fields: Any) -> None:
    """generation_records の付随フィールドを部分更新する。

    指定された field だけを SET する。``prompts`` 等の dict は JSON 文字列化、
    ``video_id`` 等の plain 型はそのまま使う。行が無ければ INSERT してから UPDATE。
    None を渡したフィールドは無視 (= 削除ではなく未指定として扱う)。"""
    sets: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if value is None:
            continue
        if key in _GEN_REC_JSON_FIELDS:
            sets.append(f"{key} = ?")
            values.append(json.dumps(value, ensure_ascii=False))
        elif key in _GEN_REC_PLAIN_FIELDS:
            sets.append(f"{key} = ?")
            values.append(value)
        else:
            raise ValueError(f"unknown generation_records field: {key}")
    if not sets:
        return
    values.append(ts)
    sql = f"UPDATE generation_records SET {', '.join(sets)} WHERE ts = ?"
    with get_connection() as conn:
        cur = conn.execute(sql, values)
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO generation_records (ts, created_at) VALUES (?, ?)",
                (ts, _now()),
            )
            conn.execute(sql, values)


# ───────────── qa_failures (Phase 0: 計測基盤) ─────────────

def insert_qa_failure(
    *,
    ts: str,
    stage: str,
    source: str,
    tags: list[str] | None = None,
    note: str | None = None,
    scene_idx: int | None = None,
    line_idx: int | None = None,
    artifact_path: str | None = None,
    screenplay_snapshot_path: str | None = None,
) -> int:
    """qa_failures に 1 行追加して新規 id を返す。"""
    tag_json = json.dumps(tags or [], ensure_ascii=False)
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO qa_failures
               (ts, stage, scene_idx, line_idx, tags, note, source,
                artifact_path, screenplay_snapshot_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, stage, scene_idx, line_idx, tag_json, note, source,
             artifact_path, screenplay_snapshot_path, _now()),
        )
        return int(cur.lastrowid or 0)


def list_qa_failures(
    *,
    ts: str | None = None,
    stage: str | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """qa_failures を絞り込んで返す。tags は JSON list として deserialize 済み。"""
    where: list[str] = []
    params: list[Any] = []
    if ts is not None:
        where.append("ts = ?")
        params.append(ts)
    if stage is not None:
        where.append("stage = ?")
        params.append(stage)
    if source is not None:
        where.append("source = ?")
        params.append(source)
    sql = "SELECT * FROM qa_failures"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
        out.append(d)
    return out


def count_qa_failures(
    *,
    ts: str | None = None,
    stage: str | None = None,
    source: str | None = None,
) -> int:
    """フィルタ条件にマッチする qa_failures の件数を返す。"""
    where: list[str] = []
    params: list[Any] = []
    if ts is not None:
        where.append("ts = ?")
        params.append(ts)
    if stage is not None:
        where.append("stage = ?")
        params.append(stage)
    if source is not None:
        where.append("source = ?")
        params.append(source)
    sql = "SELECT COUNT(*) AS c FROM qa_failures"
    if where:
        sql += " WHERE " + " AND ".join(where)
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row["c"]) if row else 0
