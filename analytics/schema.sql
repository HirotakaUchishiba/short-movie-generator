-- Analytics schema for tensyoku-movie-generator
-- Tracks screenplays, generated videos, cross-platform posts, and time-series metrics.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screenplays (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    caption TEXT,
    title_overlay TEXT,
    audio_mode TEXT,
    scene_count INTEGER,
    line_count INTEGER,
    total_duration REAL,
    hook_type TEXT,
    tone TEXT,
    dominant_emotion TEXT,
    theme TEXT,
    character_archetype TEXT,
    auto_tagged_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_screenplays_hook ON screenplays(hook_type);
CREATE INDEX IF NOT EXISTS idx_screenplays_emotion ON screenplays(dominant_emotion);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    screenplay_id TEXT NOT NULL REFERENCES screenplays(id) ON DELETE CASCADE,
    output_path TEXT NOT NULL,
    duration_sec REAL,
    generation_cost_usd REAL,
    generated_at TEXT NOT NULL,
    final_imported INTEGER NOT NULL DEFAULT 0,
    final_filename TEXT,
    final_audio_match_score REAL
);

CREATE INDEX IF NOT EXISTS idx_videos_screenplay ON videos(screenplay_id);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    platform TEXT NOT NULL CHECK(platform IN ('youtube','tiktok','instagram')),
    platform_post_id TEXT NOT NULL,
    url TEXT,
    posted_at TEXT,
    caption TEXT,
    hashtags TEXT,
    registered_at TEXT NOT NULL,
    UNIQUE(platform, platform_post_id)
);

CREATE INDEX IF NOT EXISTS idx_posts_video ON posts(video_id);
CREATE INDEX IF NOT EXISTS idx_posts_platform ON posts(platform);

CREATE TABLE IF NOT EXISTS post_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    fetched_at TEXT NOT NULL,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    saves INTEGER,
    watch_time_sec REAL,
    avg_view_duration REAL,
    completion_rate REAL,
    ctr REAL,
    raw_response TEXT
);

CREATE INDEX IF NOT EXISTS idx_metrics_post_time ON post_metrics(post_id, fetched_at);

-- Latest metrics view
CREATE VIEW IF NOT EXISTS v_latest_metrics AS
SELECT pm.*
FROM post_metrics pm
JOIN (
    SELECT post_id, MAX(fetched_at) AS latest
    FROM post_metrics
    GROUP BY post_id
) latest ON pm.post_id = latest.post_id AND pm.fetched_at = latest.latest;

-- ─────────────────────────────────────────────────────────────────
-- analyze pipeline jobs (UI 経由で参考動画から台本を生成するジョブ)
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS analyze_jobs (
    id TEXT PRIMARY KEY,                       -- analyze_<TS>_<rand6>
    video_sha256 TEXT NOT NULL,                -- reference_videos(sha256) を参照
    options_json TEXT NOT NULL,                -- AnalyzeOptions のシリアライズ
    status TEXT NOT NULL,                      -- pending|dryrunning|awaiting_confirm|running|completed|failed|cancelled
    current_phase TEXT,                        -- frames|audio|whisper|...|save
    error TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    screenplay_path TEXT,                      -- 完了時の出力パス (compose 後は完全 screenplay)
    style_name TEXT,                           -- 最後に compose した VideoStyle 名 (Stage 0 の再合成デフォルト値)
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
    phase TEXT NOT NULL,                       -- frames|audio|whisper|acoustic|bgm_detect|shots|bgm_separate|claude|save
    status TEXT NOT NULL,                      -- pending|running|completed|failed|skipped
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER,
    cost_usd REAL,
    error TEXT,
    PRIMARY KEY (job_id, phase)
);

CREATE TABLE IF NOT EXISTS reference_videos (
    sha256 TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    duration_sec REAL,
    uploaded_at TEXT NOT NULL,
    last_used_at TEXT,
    -- フルオート量産で参考動画を yt-dlp 等で fetch した経路の追跡用。
    -- 既存 (= UI upload) 経路では NULL のまま。license_status="unconfirmed" は
    -- analyze pipeline に進めない gate として Phase 1 で使う。
    source_url TEXT,
    fetched_at TEXT,
    license_status TEXT DEFAULT 'unconfirmed'
);

-- ─────────────────────────────────────────────────────────────────
-- Phase 0: フルオート量産経路の計測基盤
-- (詳細は docs/plannings/2026-05-07_full-automation-implementation-plan.md §2)
-- ─────────────────────────────────────────────────────────────────

-- 1 project (= temp/<TS>) の生成履歴。video_id は ingest_video.py 完了後に
-- backfill される (= snapshot 完成前の段階でも ts ベースで stage_runs を
-- append できるよう PK は ts)。
CREATE TABLE IF NOT EXISTS generation_records (
    ts TEXT PRIMARY KEY,
    video_id TEXT REFERENCES videos(id),
    reference_video_id TEXT REFERENCES reference_videos(sha256),
    screenplay_sha TEXT,
    stage_runs TEXT NOT NULL DEFAULT '[]',
    prompts TEXT NOT NULL DEFAULT '{}',
    seeds TEXT NOT NULL DEFAULT '{}',
    api_meta TEXT NOT NULL DEFAULT '{}',
    total_cost_usd REAL NOT NULL DEFAULT 0,
    validator_scores TEXT,
    status TEXT NOT NULL DEFAULT 'in_progress',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_genrec_video ON generation_records(video_id);
CREATE INDEX IF NOT EXISTS idx_genrec_status ON generation_records(status);

-- QA 不良サンプルの台帳。Phase 0 では UI reject + regenerate 暗黙アーカイブ、
-- Phase 1 で auto_flagged、Phase 3 で post_publish_lowperf を追加していく。
CREATE TABLE IF NOT EXISTS qa_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    stage TEXT NOT NULL,
    scene_idx INTEGER,
    line_idx INTEGER,
    tags TEXT NOT NULL DEFAULT '[]',
    note TEXT,
    source TEXT NOT NULL,
    artifact_path TEXT,
    screenplay_snapshot_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_qaf_ts ON qa_failures(ts);
CREATE INDEX IF NOT EXISTS idx_qaf_stage ON qa_failures(stage);
CREATE INDEX IF NOT EXISTS idx_qaf_source ON qa_failures(source);

-- Performance summary (screenplay × platform latest metrics)
CREATE VIEW IF NOT EXISTS v_performance AS
SELECT
    s.id AS screenplay_id,
    s.name AS screenplay_name,
    s.hook_type,
    s.tone,
    s.dominant_emotion,
    s.theme,
    v.id AS video_id,
    v.output_path,
    v.generation_cost_usd,
    p.id AS post_id,
    p.platform,
    p.url,
    p.posted_at,
    m.views,
    m.likes,
    m.comments,
    m.shares,
    m.saves,
    m.completion_rate,
    m.avg_view_duration,
    m.fetched_at
FROM screenplays s
JOIN videos v ON v.screenplay_id = s.id
LEFT JOIN posts p ON p.video_id = v.id
LEFT JOIN v_latest_metrics m ON m.post_id = p.id;
