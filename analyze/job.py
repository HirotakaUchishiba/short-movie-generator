"""analyze ジョブの永続化と状態機械。

通常フロー:
    pending → running → completed
                     → failed
                     → cancelled

dryrun + コストゲートフロー (Phase 5 で活用):
    pending → dryrunning → awaiting_confirm → running → completed

各ジョブは PHASES と同数の analyze_phases 行を持ち、フェーズごとに
started_at / finished_at / duration_ms / cost_usd / error を蓄積する。
"""
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from . import store as _store

logger = logging.getLogger(__name__)

JOB_STATUSES = (
    "pending",
    "dryrunning",
    "awaiting_confirm",
    "running",
    "completed",
    "failed",
    "cancelled",
)
PHASE_STATUSES = ("pending", "running", "completed", "failed", "skipped")
PHASES = (
    "frames",
    "audio",
    "whisper",
    "acoustic",
    "claude",
    "save",
)

REFERENCE_VIDEOS_DIR = Path(config.BASE_DIR) / "assets" / "reference_videos"
ALLOWED_VIDEO_EXTS = (".mov", ".mp4", ".webm", ".mkv")


def reference_video_path(sha256: str) -> str | None:
    """sha256 に対応する reference video のファイルパスを返す。無ければ None。"""
    for ext in ALLOWED_VIDEO_EXTS:
        p = REFERENCE_VIDEOS_DIR / f"{sha256}{ext}"
        if p.exists():
            return str(p)
    return None


def reference_videos_dir() -> Path:
    REFERENCE_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    return REFERENCE_VIDEOS_DIR


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
    project_ts: str | None = None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    cancellation_requested: int = 0

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AnalyzeJob":
        fields = cls.__dataclass_fields__
        return cls(**{k: row[k] for k in row.keys() if k in fields})

    @property
    def options(self) -> dict:
        return json.loads(self.options_json)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_job_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"analyze_{ts}_{uuid.uuid4().hex[:6]}"


# ─── Job CRUD ───────────────────────────────────────────────────


def create_job(
    video_sha256: str, options: dict,
    *, project_ts: str | None = None,
) -> AnalyzeJob:
    """新規 analyze ジョブを作成し PHASES の行も初期化する。

    project_ts: from-reference-video 経路 (= POST /api/projects/from-reference-video)
        で渡される project の TS (= temp/<TS>)。save phase 完了 hook が
        この TS を見て metadata + Stage 1 unlock を行う。production の唯一の
        caller は必ず project_ts を渡し、None は test fixture が直接呼ぶ
        ときの test-only path として残してある (= 旧 standalone analyze
        経路は Phase E (#182) で削除済)。
    """
    job_id = _new_job_id()
    options_json = json.dumps(options, ensure_ascii=False, sort_keys=True)
    created_at = _now()

    with _store.get_connection() as conn:
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
    logger.info(
        "analyze job created: %s (video=%s, project_ts=%s)",
        job_id, video_sha256[:12], project_ts,
    )
    return get_job(job_id)


def get_job(job_id: str) -> AnalyzeJob:
    with _store.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM analyze_jobs WHERE id = ?", (job_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"analyze_job not found: {job_id}")
    return AnalyzeJob.from_row(row)


def list_jobs(limit: int = 50) -> list[AnalyzeJob]:
    with _store.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM analyze_jobs ORDER BY created_at DESC LIMIT ?", (limit,),
        ).fetchall()
    return [AnalyzeJob.from_row(r) for r in rows]


def update_job(job_id: str, **kwargs: Any) -> None:
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [job_id]
    with _store.get_connection() as conn:
        conn.execute(f"UPDATE analyze_jobs SET {sets} WHERE id = ?", values)


def transition_status(job_id: str, new_status: str, **extra: Any) -> AnalyzeJob:
    """status 遷移 + 関連フィールドの更新。

    new_status="running" なら started_at を、終端状態なら finished_at を
    自動でセットする (extra で明示的に渡されていれば優先)。
    """
    if new_status not in JOB_STATUSES:
        raise ValueError(f"invalid status: {new_status}")
    extra["status"] = new_status
    if new_status == "running" and "started_at" not in extra:
        extra["started_at"] = _now()
    if new_status in ("completed", "failed", "cancelled") and "finished_at" not in extra:
        extra["finished_at"] = _now()
    update_job(job_id, **extra)
    return get_job(job_id)


def request_cancellation(job_id: str) -> None:
    update_job(job_id, cancellation_requested=1)


def is_cancellation_requested(job_id: str) -> bool:
    return bool(get_job(job_id).cancellation_requested)


# ─── Phase tracking ─────────────────────────────────────────────


def start_phase(job_id: str, phase: str) -> None:
    with _store.get_connection() as conn:
        conn.execute(
            """UPDATE analyze_phases
               SET status = 'running', started_at = ?
               WHERE job_id = ? AND phase = ?""",
            (_now(), job_id, phase),
        )
        conn.execute(
            "UPDATE analyze_jobs SET current_phase = ? WHERE id = ?",
            (phase, job_id),
        )


def complete_phase(job_id: str, phase: str, *,
                    duration_ms: int | None = None,
                    cost_usd: float | None = None) -> None:
    with _store.get_connection() as conn:
        conn.execute(
            """UPDATE analyze_phases
               SET status = 'completed', finished_at = ?,
                   duration_ms = ?, cost_usd = ?
               WHERE job_id = ? AND phase = ?""",
            (_now(), duration_ms, cost_usd, job_id, phase),
        )


def fail_phase(job_id: str, phase: str, error: str) -> None:
    with _store.get_connection() as conn:
        conn.execute(
            """UPDATE analyze_phases
               SET status = 'failed', finished_at = ?, error = ?
               WHERE job_id = ? AND phase = ?""",
            (_now(), error, job_id, phase),
        )


def skip_phase(job_id: str, phase: str) -> None:
    with _store.get_connection() as conn:
        conn.execute(
            """UPDATE analyze_phases
               SET status = 'skipped', finished_at = ?
               WHERE job_id = ? AND phase = ?""",
            (_now(), job_id, phase),
        )


def get_phases(job_id: str) -> list[dict]:
    with _store.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM analyze_phases WHERE job_id = ? ORDER BY phase",
            (job_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ─── Reference videos ───────────────────────────────────────────


def upsert_reference_video(sha256: str, *, original_name: str,
                            size_bytes: int,
                            duration_sec: float | None = None) -> None:
    """アップロード動画のメタデータを登録。既存の sha256 なら last_used_at を更新。"""
    now = _now()
    with _store.get_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM reference_videos WHERE sha256 = ?", (sha256,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE reference_videos SET last_used_at = ? WHERE sha256 = ?",
                (now, sha256),
            )
            return
        conn.execute(
            """INSERT INTO reference_videos
               (sha256, original_name, size_bytes, duration_sec, uploaded_at)
               VALUES (?, ?, ?, ?, ?)""",
            (sha256, original_name, size_bytes, duration_sec, now),
        )


def get_reference_video(sha256: str) -> dict | None:
    with _store.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM reference_videos WHERE sha256 = ?", (sha256,),
        ).fetchone()
    return dict(row) if row else None


def list_reference_videos() -> list[dict]:
    with _store.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM reference_videos ORDER BY uploaded_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def touch_reference_video(sha256: str) -> None:
    with _store.get_connection() as conn:
        conn.execute(
            "UPDATE reference_videos SET last_used_at = ? WHERE sha256 = ?",
            (_now(), sha256),
        )


def delete_reference_video(sha256: str, *, force: bool = False) -> bool:
    """動画メタデータを削除する。

    既定 (force=False) では analyze_jobs から参照されていない場合のみ削除する。
    force=True では関連 analyze_jobs も先に削除してから動画を消す
    (analyze_phases は schema.sql の ON DELETE CASCADE で自動連鎖)。

    Returns:
        True なら削除成功、False は force=False かつ参照ジョブが残っている場合のみ。
    """
    with _store.get_connection() as conn:
        if not force:
            used = conn.execute(
                "SELECT 1 FROM analyze_jobs WHERE video_sha256 = ? LIMIT 1",
                (sha256,),
            ).fetchone()
            if used:
                return False
        else:
            conn.execute(
                "DELETE FROM analyze_jobs WHERE video_sha256 = ?", (sha256,),
            )
        conn.execute("DELETE FROM reference_videos WHERE sha256 = ?", (sha256,))
        return True


def count_jobs_for_video(sha256: str) -> int:
    """指定動画を参照する analyze_jobs の件数。409 エラー時の表示用。"""
    with _store.get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM analyze_jobs WHERE video_sha256 = ?",
            (sha256,),
        ).fetchone()
    return row[0] if row else 0
