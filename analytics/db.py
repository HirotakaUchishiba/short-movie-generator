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
CURRENT_SCHEMA_VERSION = 1


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
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = (row["v"] or 0) if row else 0
        if current < CURRENT_SCHEMA_VERSION:
            conn.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES(?, ?)",
                (CURRENT_SCHEMA_VERSION, _now()),
            )
    logger.info("analytics DB initialized at %s", _db_path())


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


def insert_video(video_id: str, screenplay_id: str, output_path: str,
                 duration_sec: float | None = None,
                 generation_cost_usd: float | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO videos
               (id, screenplay_id, output_path, duration_sec, generation_cost_usd, generated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (video_id, screenplay_id, os.path.abspath(output_path),
             duration_sec, generation_cost_usd, _now()),
        )
        logger.info("video %s (screenplay=%s) 登録", video_id, screenplay_id)


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
