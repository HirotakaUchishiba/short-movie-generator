"""analyze ジョブ専用の sqlite 永続化 (= ``data/analyze.db``)。

analyze 側のロジック (= job.py / runner.py 他) は本モジュール経由でだけ DB に
触る。動画公開・公開後分析を責務から外したのに伴い、元 analytics.db を間借り
していた経路を廃止し、analyze 専用 DB ファイルに分離した。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

import config

DB_PATH = os.path.join(config.BASE_DIR, "data", "analyze.db")

_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS reference_videos (
    sha256 TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    duration_sec REAL,
    uploaded_at TEXT NOT NULL,
    last_used_at TEXT,
    source_url TEXT,
    fetched_at TEXT,
    license_status TEXT DEFAULT 'unconfirmed'
);

CREATE TABLE IF NOT EXISTS analyze_jobs (
    id TEXT PRIMARY KEY,
    video_sha256 TEXT NOT NULL,
    options_json TEXT NOT NULL,
    status TEXT NOT NULL,
    current_phase TEXT,
    error TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    screenplay_path TEXT,
    style_name TEXT,
    project_ts TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_analyze_jobs_video ON analyze_jobs(video_sha256);
CREATE INDEX IF NOT EXISTS idx_analyze_jobs_status ON analyze_jobs(status);
CREATE INDEX IF NOT EXISTS idx_analyze_jobs_created ON analyze_jobs(created_at);

CREATE TABLE IF NOT EXISTS analyze_phases (
    job_id TEXT NOT NULL REFERENCES analyze_jobs(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER,
    cost_usd REAL,
    error TEXT,
    PRIMARY KEY (job_id, phase)
);
"""


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def ensure_schema() -> None:
    """analyze 専用 table の存在を保証する (= 起動時 + テスト初期化)。"""
    _ensure_dir()
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(_SCHEMA_SQL)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """analyze ジョブ永続化用 sqlite 接続を返す (= row_factory + 自動 commit)。"""
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()
