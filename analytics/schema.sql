-- Analytics schema for short-movie-generator
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
    auto_tagged_at TEXT,
    -- schema v11: content-strategy.md Phase 1 の概念モデル。flat な ``theme`` の
    -- 上位概念として transformation (= 視聴者にもたらす変化) / tree_main_branch
    -- (= 4 主要課題のいずれか) / pov_id (= クリエイター視点) を追加。Halo effect
    -- 計測 (= v_halo_effect) は transformation を join key に使う。
    transformation TEXT,
    tree_main_branch TEXT,
    pov_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_screenplays_hook ON screenplays(hook_type);
CREATE INDEX IF NOT EXISTS idx_screenplays_emotion ON screenplays(dominant_emotion);
CREATE INDEX IF NOT EXISTS idx_screenplays_transformation ON screenplays(transformation);
CREATE INDEX IF NOT EXISTS idx_screenplays_branch ON screenplays(tree_main_branch);

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
    rollback_at TEXT,
    rollback_reason TEXT,
    UNIQUE(platform, platform_post_id)
);

CREATE INDEX IF NOT EXISTS idx_posts_video ON posts(video_id);
CREATE INDEX IF NOT EXISTS idx_posts_platform ON posts(platform);

-- schema v9: rollback されていない post だけを返す view。
-- dashboard / fetch_metrics / v_strategy_performance はこの view を読むことで
-- 取り下げ済 post の metrics polling や reward 集計を自動的に止める。
CREATE VIEW IF NOT EXISTS v_active_posts AS
SELECT * FROM posts WHERE rollback_at IS NULL;

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
    -- schema v10: PDCA 中核 KPI。content-strategy.md がフック / 80-20 ルール /
    -- アルゴリズム適合 / Halo effect プロキシとして要求する 6 指標。
    impressions INTEGER,
    subscribers_gained INTEGER,
    traffic_browse_pct REAL,
    traffic_suggested_pct REAL,
    traffic_search_pct REAL,
    traffic_external_pct REAL,
    raw_response TEXT
);

CREATE INDEX IF NOT EXISTS idx_metrics_post_time ON post_metrics(post_id, fetched_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_metrics_post_fetched ON post_metrics(post_id, fetched_at);

-- schema v10: 動画内 elapsed % vs audience watch ratio の time-series。
-- YouTube Analytics の dimension=elapsedVideoTimeRatio で取得し、30 秒地点 /
-- フックの強さ (= content-strategy.md L57, L242-247) を後段で算出する素材。
CREATE TABLE IF NOT EXISTS post_retention_curves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    fetched_at TEXT NOT NULL,
    elapsed_pct REAL NOT NULL,
    elapsed_sec REAL,
    ratio REAL NOT NULL,
    raw_response TEXT,
    UNIQUE(post_id, fetched_at, elapsed_pct)
);

CREATE INDEX IF NOT EXISTS idx_retention_post_time
ON post_retention_curves(post_id, fetched_at);

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

-- ─────────────────────────────────────────────────────────────────
-- Phase 3: closed-loop 改善 (= experiment_assignments + 軸別 view)
-- ─────────────────────────────────────────────────────────────────

-- 1 video の各軸で「今回どの値を試したか」+「strategy (= baseline / shadow_explore
-- / shadow_exploit / active_explore / active_exploit)」+「Haiku が事後 tag した
-- 観測値」を記録する。video_id は ts (= temp dir timestamp) を入れ、ingest_video
-- 後に videos.id (= 同じ ts) と join できる。FK 制約は付けていない (= record_assignments
-- が ingest_video より先に走るため)。observed_value は improvement.observed.back_fill
-- が screenplays.<axis> から後で書き込む。
CREATE TABLE IF NOT EXISTS experiment_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    axis TEXT NOT NULL,
    selected_value TEXT NOT NULL,
    strategy TEXT NOT NULL,
    observed_value TEXT,
    -- schema v8 (Phase X-1): scene 粒度 + composition identity 列。
    -- 既存 Phase 3 の動画粒度書き込みは scene_idx=NULL で続行可能。
    scene_idx INTEGER,
    composition_id TEXT,
    composition_version TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_exp_video ON experiment_assignments(video_id);
CREATE INDEX IF NOT EXISTS idx_exp_axis ON experiment_assignments(axis);
CREATE INDEX IF NOT EXISTS idx_exp_strategy ON experiment_assignments(strategy);

-- 軸別パフォーマンス view (= bandit の reward source)。
-- 旧 v_axis_performance は 4 軸を同時 GROUP BY していたため、1 軸だけ問い合わせる
-- と他 3 軸の組合せ別に行が分かれて重複していた。schema v7 で軸ごとに分離。
-- 各 view は post 投稿後 24h 経過したメトリクスのみ採用 (= まだ伸びていない動画の
-- ノイズを排除)。
CREATE VIEW IF NOT EXISTS v_hook_type_performance AS
SELECT
    s.hook_type AS axis_value,
    COUNT(*) AS n,
    AVG(m.views) AS avg_views,
    AVG(m.completion_rate) AS avg_completion,
    AVG(m.saves) AS avg_save
FROM screenplays s
JOIN videos v ON v.screenplay_id = s.id
JOIN posts p ON p.video_id = v.id
LEFT JOIN v_latest_metrics m ON m.post_id = p.id
WHERE m.fetched_at IS NOT NULL
  AND p.posted_at IS NOT NULL
  AND julianday(m.fetched_at) - julianday(p.posted_at) >= 1.0
  AND s.hook_type IS NOT NULL
GROUP BY s.hook_type;

CREATE VIEW IF NOT EXISTS v_tone_performance AS
SELECT
    s.tone AS axis_value,
    COUNT(*) AS n,
    AVG(m.views) AS avg_views,
    AVG(m.completion_rate) AS avg_completion,
    AVG(m.saves) AS avg_save
FROM screenplays s
JOIN videos v ON v.screenplay_id = s.id
JOIN posts p ON p.video_id = v.id
LEFT JOIN v_latest_metrics m ON m.post_id = p.id
WHERE m.fetched_at IS NOT NULL
  AND p.posted_at IS NOT NULL
  AND julianday(m.fetched_at) - julianday(p.posted_at) >= 1.0
  AND s.tone IS NOT NULL
GROUP BY s.tone;

CREATE VIEW IF NOT EXISTS v_dominant_emotion_performance AS
SELECT
    s.dominant_emotion AS axis_value,
    COUNT(*) AS n,
    AVG(m.views) AS avg_views,
    AVG(m.completion_rate) AS avg_completion,
    AVG(m.saves) AS avg_save
FROM screenplays s
JOIN videos v ON v.screenplay_id = s.id
JOIN posts p ON p.video_id = v.id
LEFT JOIN v_latest_metrics m ON m.post_id = p.id
WHERE m.fetched_at IS NOT NULL
  AND p.posted_at IS NOT NULL
  AND julianday(m.fetched_at) - julianday(p.posted_at) >= 1.0
  AND s.dominant_emotion IS NOT NULL
GROUP BY s.dominant_emotion;

CREATE VIEW IF NOT EXISTS v_theme_performance AS
SELECT
    s.theme AS axis_value,
    COUNT(*) AS n,
    AVG(m.views) AS avg_views,
    AVG(m.completion_rate) AS avg_completion,
    AVG(m.saves) AS avg_save
FROM screenplays s
JOIN videos v ON v.screenplay_id = s.id
JOIN posts p ON p.video_id = v.id
LEFT JOIN v_latest_metrics m ON m.post_id = p.id
WHERE m.fetched_at IS NOT NULL
  AND p.posted_at IS NOT NULL
  AND julianday(m.fetched_at) - julianday(p.posted_at) >= 1.0
  AND s.theme IS NOT NULL
GROUP BY s.theme;

-- schema v9 (Phase 3.5 / 4.5): strategy × axis 別パフォーマンス view。
-- experiment_assignments.strategy ("baseline" / "shadow_*" / "active_*") ごとに
-- reward を分離するため、軸別 view と join せず experiment_assignments を直接読む。
-- baseline と active で生成方法が違うので reward を混ぜない (= A/B 検定の正確性)。
-- v_active_posts を使うので rollback 済 post は自動除外。
-- experiment_assignments.video_id は schema v6 で TEXT (FK 無し) なので、ts と
-- videos.id の両方に対応するため LEFT JOIN で video が見つからなかったケースも
-- 拾える設計。ingest_video の backfill で ts → videos.id 置換が起きるまで両方走る。
CREATE VIEW IF NOT EXISTS v_strategy_performance AS
SELECT
    e.strategy,
    e.axis,
    e.selected_value,
    COUNT(*) AS n,
    AVG(m.views) AS avg_views,
    AVG(m.completion_rate) AS avg_completion,
    AVG(m.saves) AS avg_save
FROM experiment_assignments e
LEFT JOIN videos v ON v.id = e.video_id
JOIN v_active_posts p ON p.video_id = COALESCE(v.id, e.video_id)
LEFT JOIN v_latest_metrics m ON m.post_id = p.id
WHERE m.fetched_at IS NOT NULL
  AND p.posted_at IS NOT NULL
  AND julianday(m.fetched_at) - julianday(p.posted_at) >= 1.0
GROUP BY e.strategy, e.axis, e.selected_value;

-- Performance summary (screenplay × platform latest metrics).
-- v_active_posts 経由で rollback 済 post を自動除外する (= schema v9 の v_active_posts
-- 整備に追従)。dashboard / 概要集計が取り下げ済み投稿の metrics を混ぜないようにする。
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
LEFT JOIN v_active_posts p ON p.video_id = v.id
LEFT JOIN v_latest_metrics m ON m.post_id = p.id;

-- schema v11: transformation × branch 単位の集計。content-strategy.md Phase 1 の
-- "Transformation 軸の一貫性" を経験ではなくデータで判定する正本 view。
-- 24h 経過 metrics のみ採用 (= 軸別 view と同ノイズ排除ポリシー)。
CREATE VIEW IF NOT EXISTS v_transformation_performance AS
SELECT
    s.transformation,
    s.tree_main_branch,
    COUNT(DISTINCT p.id) AS n,
    AVG(m.views) AS avg_views,
    AVG(m.completion_rate) AS avg_completion,
    AVG(m.ctr) AS avg_ctr,
    SUM(m.subscribers_gained) AS sum_subs_gained
FROM screenplays s
JOIN videos v ON v.screenplay_id = s.id
JOIN v_active_posts p ON p.video_id = v.id
LEFT JOIN v_latest_metrics m ON m.post_id = p.id
WHERE m.fetched_at IS NOT NULL
  AND p.posted_at IS NOT NULL
  AND julianday(m.fetched_at) - julianday(p.posted_at) >= 1.0
  AND s.transformation IS NOT NULL
GROUP BY s.transformation, s.tree_main_branch;

-- schema v11: Halo effect の簡易ビュー。SQLite に STDEV が無いため、ヒット動画の
-- 厳密な統計検定は dashboard / app side に委ねる。view は transformation 別に
-- peak (= ヒット候補) / avg (= 通常水準) / 合計獲得登録者を出すだけ。
-- dashboard で peak/avg 比や total_subs_gained を見て halo の有無を判断する。
CREATE VIEW IF NOT EXISTS v_halo_effect AS
SELECT
    s.transformation,
    COUNT(DISTINCT p.id) AS n_posts,
    AVG(m.views) AS avg_views,
    MAX(m.views) AS peak_views,
    COALESCE(SUM(m.subscribers_gained), 0) AS total_subs_gained,
    MAX(p.posted_at) AS latest_post_at
FROM screenplays s
JOIN videos v ON v.screenplay_id = s.id
JOIN v_active_posts p ON p.video_id = v.id
LEFT JOIN v_latest_metrics m ON m.post_id = p.id
WHERE s.transformation IS NOT NULL
  AND m.fetched_at IS NOT NULL
  AND p.posted_at IS NOT NULL
  AND julianday(m.fetched_at) - julianday(p.posted_at) >= 1.0
GROUP BY s.transformation;
