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
    generated_at TEXT NOT NULL
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
