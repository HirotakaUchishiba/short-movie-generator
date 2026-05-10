"""Phase A: query_post_metrics_timeseries / list_generation_records /
v_performance 経由 v_active_posts のテスト。"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def _seed_post_with_metrics(db, *, ts: str, fetched_offsets_min: list[int]):
    """ts 単位で screenplay / video / post を作り、fetched_at を分単位でずらして
    post_metrics を投入する。fetched_offsets_min は post 作成からの経過分。"""
    sp_id = f"sp_{ts}"
    v_id = f"v_{ts}"
    p_id = f"p_{ts}"
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO screenplays (id, path, name, sha256, created_at, raw_json) "
            "VALUES (?, '/x', 'x', ?, datetime('now'), '{}')",
            (sp_id, sp_id + "_sha"),
        )
        conn.execute(
            "INSERT INTO videos (id, screenplay_id, output_path, generated_at, "
            "generation_cost_usd) VALUES (?, ?, '/x', datetime('now'), 5.0)",
            (v_id, sp_id),
        )
        conn.execute(
            "INSERT INTO posts (id, video_id, platform, platform_post_id, "
            "posted_at, registered_at) "
            "VALUES (?, ?, 'youtube', ?, datetime('now'), datetime('now'))",
            (p_id, v_id, p_id),
        )
        for i, off in enumerate(fetched_offsets_min):
            conn.execute(
                "INSERT INTO post_metrics (post_id, fetched_at, views) "
                "VALUES (?, datetime('now', ?), ?)",
                (p_id, f"+{off} minutes", 100 * (i + 1)),
            )
    return p_id


def test_query_post_metrics_timeseries_orders_by_fetched_at(isolated_db):
    db = isolated_db
    p_id = _seed_post_with_metrics(db, ts="t1", fetched_offsets_min=[0, 30, 60])
    rows = db.query_post_metrics_timeseries(p_id)
    assert len(rows) == 3
    fetched = [r["fetched_at"] for r in rows]
    assert fetched == sorted(fetched), "fetched_at で昇順ソートされていない"
    views = [r["views"] for r in rows]
    assert views == [100, 200, 300]


def test_query_post_metrics_timeseries_filters_by_post_id(isolated_db):
    db = isolated_db
    p_a = _seed_post_with_metrics(db, ts="a", fetched_offsets_min=[0])
    _ = _seed_post_with_metrics(db, ts="b", fetched_offsets_min=[0, 10])
    rows = db.query_post_metrics_timeseries(p_a)
    assert len(rows) == 1
    assert rows[0]["post_id"] == p_a


def test_query_post_metrics_timeseries_respects_limit(isolated_db):
    db = isolated_db
    p_id = _seed_post_with_metrics(db, ts="lim", fetched_offsets_min=[0, 10, 20, 30])
    rows = db.query_post_metrics_timeseries(p_id, limit=2)
    assert len(rows) == 2


def test_list_generation_records_deserializes_validator_scores(isolated_db):
    db = isolated_db
    scores = {"audio_match": 0.92, "char_drift": 0.13}
    db.update_generation_record(
        ts="ts_alpha", validator_scores=scores, status="completed",
    )
    rows = db.list_generation_records()
    assert len(rows) == 1
    assert rows[0]["ts"] == "ts_alpha"
    assert rows[0]["validator_scores"] == scores


def test_list_generation_records_filters_by_status(isolated_db):
    db = isolated_db
    db.update_generation_record(ts="ts_done", status="completed")
    db.update_generation_record(ts="ts_run", status="in_progress")
    rows = db.list_generation_records(status="completed")
    tss = {r["ts"] for r in rows}
    assert tss == {"ts_done"}


def test_list_generation_records_orders_by_created_at_desc(isolated_db):
    db = isolated_db
    # datetime('now') は秒精度で tie-break が不定なので、created_at を明示する。
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO generation_records (ts, status, created_at) "
            "VALUES (?, 'completed', datetime('now', '-1 hour'))",
            ("t_old",),
        )
        conn.execute(
            "INSERT INTO generation_records (ts, status, created_at) "
            "VALUES (?, 'completed', datetime('now'))",
            ("t_new",),
        )
    rows = db.list_generation_records(limit=10)
    tss = [r["ts"] for r in rows]
    assert tss[0] == "t_new"
    assert tss[1] == "t_old"


def test_v_performance_excludes_rolled_back_posts(isolated_db):
    """A-5: v_performance が v_active_posts 経由になっているか。"""
    db = isolated_db
    p_active = _seed_post_with_metrics(db, ts="active", fetched_offsets_min=[0])
    p_rolled = _seed_post_with_metrics(db, ts="rolled", fetched_offsets_min=[0])
    db.mark_post_rolled_back(p_rolled, reason="test")

    rows = db.query_performance()
    post_ids = {r["post_id"] for r in rows if r["post_id"]}
    assert p_active in post_ids
    assert p_rolled not in post_ids, (
        "v_performance に rollback 済 post が混入している (= v_active_posts 経由になっていない)"
    )


def _seed_axis_post(db, *, ts: str, hook_type: str, tone: str,
                    dominant_emotion: str, theme: str, views: int):
    """軸別 view 用 seed: screenplay に 4 軸値を入れ、24h+1min 経過した
    post_metrics を 1 件投入する。"""
    sp_id = f"sp_{ts}"
    v_id = f"v_{ts}"
    p_id = f"p_{ts}"
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO screenplays (id, path, name, sha256, created_at, "
            "raw_json, hook_type, tone, dominant_emotion, theme) "
            "VALUES (?, '/x', 'x', ?, datetime('now'), '{}', ?, ?, ?, ?)",
            (sp_id, sp_id + "_sha", hook_type, tone, dominant_emotion, theme),
        )
        conn.execute(
            "INSERT INTO videos (id, screenplay_id, output_path, generated_at, "
            "generation_cost_usd) VALUES (?, ?, '/x', datetime('now'), 5.0)",
            (v_id, sp_id),
        )
        # posted_at は 2 日前にして 24h 経過 filter (julianday >= 1.0) を通す。
        conn.execute(
            "INSERT INTO posts (id, video_id, platform, platform_post_id, "
            "posted_at, registered_at) "
            "VALUES (?, ?, 'youtube', ?, datetime('now', '-2 days'), datetime('now'))",
            (p_id, v_id, p_id),
        )
        conn.execute(
            "INSERT INTO post_metrics (post_id, fetched_at, views) "
            "VALUES (?, datetime('now'), ?)",
            (p_id, views),
        )
    return p_id


@pytest.mark.parametrize("view_name,axis_column,axis_value", [
    ("v_hook_type_performance", "hook_type", "shock"),
    ("v_tone_performance", "tone", "casual"),
    ("v_dominant_emotion_performance", "dominant_emotion", "驚き"),
    ("v_theme_performance", "theme", "tech"),
])
def test_axis_views_exclude_rolled_back_posts(
    isolated_db, view_name, axis_column, axis_value,
):
    """schema v12 / D-1: 軸別 view 4 つが v_active_posts 経由で
    rollback 済 post を集計から除外しているか。"""
    db = isolated_db
    common = dict(
        hook_type="shock", tone="casual",
        dominant_emotion="驚き", theme="tech",
    )
    p_active = _seed_axis_post(db, ts="active", views=100, **common)
    p_rolled = _seed_axis_post(db, ts="rolled", views=999, **common)
    db.mark_post_rolled_back(p_rolled, reason="test")

    with db.get_connection() as conn:
        rows = list(conn.execute(
            f"SELECT axis_value, n, avg_views FROM {view_name} "
            f"WHERE axis_value = ?",
            (axis_value,),
        ))

    assert len(rows) == 1, f"{view_name} で {axis_column}={axis_value} が見つからない"
    row = rows[0]
    assert row["n"] == 1, (
        f"{view_name} に rollback 済 post が混入している "
        f"(n={row['n']}, expected=1, axis={axis_column})"
    )
    assert row["avg_views"] == 100.0, (
        f"{view_name} の avg_views に rollback 済 post の views=999 が混じっている "
        f"(actual={row['avg_views']}, expected=100.0)"
    )


def test_list_generation_records_handles_invalid_validator_scores(isolated_db):
    """validator_scores が壊れた JSON を保持していても落ちないことを確認。"""
    db = isolated_db
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO generation_records (ts, validator_scores, created_at) "
            "VALUES (?, ?, datetime('now'))",
            ("broken", "{this is not json", ),
        )
    rows = db.list_generation_records(limit=10)
    assert any(r["ts"] == "broken" for r in rows)
    broken = next(r for r in rows if r["ts"] == "broken")
    assert isinstance(broken["validator_scores"], str)


def test_list_generation_records_validator_scores_can_be_dumped(isolated_db):
    """deserialize 後の dict が JSON 再シリアライズ可能 (= dashboard で扱える)。"""
    db = isolated_db
    db.update_generation_record(
        ts="ok", validator_scores={"a": 1.0, "b": 0.5}, status="completed",
    )
    rec = db.list_generation_records(limit=1)[0]
    payload = json.dumps(rec["validator_scores"])
    assert "a" in payload
