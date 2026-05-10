"""Phase B: post_metrics v10 列 + post_retention_curves のテスト。"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def _seed_post(db, *, ts: str = "t1") -> str:
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
            "INSERT INTO videos (id, screenplay_id, output_path, generated_at) "
            "VALUES (?, ?, '/x', datetime('now'))",
            (v_id, sp_id),
        )
        conn.execute(
            "INSERT INTO posts (id, video_id, platform, platform_post_id, "
            "posted_at, registered_at) "
            "VALUES (?, ?, 'youtube', ?, datetime('now'), datetime('now'))",
            (p_id, v_id, p_id),
        )
    return p_id


# ───────────── post_metrics v10 列 ─────────────

def test_insert_metrics_persists_v10_columns(isolated_db):
    db = isolated_db
    p_id = _seed_post(db)
    db.insert_metrics(p_id, {
        "views": 1000,
        "impressions": 25000,
        "ctr": 0.04,
        "subscribers_gained": 12,
        "traffic_browse_pct": 0.55,
        "traffic_suggested_pct": 0.30,
        "traffic_search_pct": 0.10,
        "traffic_external_pct": 0.05,
    })
    rows = db.query_post_metrics_timeseries(p_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["impressions"] == 25000
    assert row["ctr"] == pytest.approx(0.04)
    assert row["subscribers_gained"] == 12
    assert row["traffic_browse_pct"] == pytest.approx(0.55)
    assert row["traffic_suggested_pct"] == pytest.approx(0.30)
    assert row["traffic_search_pct"] == pytest.approx(0.10)
    assert row["traffic_external_pct"] == pytest.approx(0.05)


def test_insert_metrics_v10_columns_default_to_null(isolated_db):
    db = isolated_db
    p_id = _seed_post(db)
    db.insert_metrics(p_id, {"views": 100})
    row = db.query_post_metrics_timeseries(p_id)[0]
    for k in ("impressions", "subscribers_gained", "traffic_browse_pct",
              "traffic_suggested_pct", "traffic_search_pct", "traffic_external_pct"):
        assert row[k] is None, f"{k} は metrics dict に無いと NULL のはず"


# ───────────── post_retention_curves ─────────────

def test_insert_retention_curve_inserts_all_points(isolated_db):
    db = isolated_db
    p_id = _seed_post(db)
    curve = [
        {"elapsed_pct": 0.0, "ratio": 1.0, "elapsed_sec": 0.0},
        {"elapsed_pct": 0.5, "ratio": 0.6, "elapsed_sec": 30.0},
        {"elapsed_pct": 1.0, "ratio": 0.2, "elapsed_sec": 60.0},
    ]
    inserted = db.insert_retention_curve(p_id, curve)
    assert inserted == 3
    rows = db.query_retention_curve(p_id)
    assert len(rows) == 3
    assert rows[0]["elapsed_pct"] == pytest.approx(0.0)
    assert rows[-1]["elapsed_pct"] == pytest.approx(1.0)


def test_insert_retention_curve_unique_constraint(isolated_db):
    db = isolated_db
    p_id = _seed_post(db)
    # 同じ fetched_at で 2 回投入 → 2 回目は INSERT OR IGNORE で 0 件
    fetched_at = "2026-05-10T12:00:00+00:00"
    curve = [{"elapsed_pct": 0.5, "ratio": 0.7}]
    a = db.insert_retention_curve(p_id, curve, fetched_at=fetched_at)
    b = db.insert_retention_curve(p_id, curve, fetched_at=fetched_at)
    assert a == 1
    assert b == 0


def test_insert_retention_curve_different_fetched_at_accumulates(isolated_db):
    db = isolated_db
    p_id = _seed_post(db)
    curve = [{"elapsed_pct": 0.5, "ratio": 0.7}]
    db.insert_retention_curve(p_id, curve, fetched_at="2026-05-10T12:00:00+00:00")
    db.insert_retention_curve(p_id, curve, fetched_at="2026-05-11T12:00:00+00:00")
    # query_retention_curve は最新 fetched_at のみ返す
    latest = db.query_retention_curve(p_id)
    assert len(latest) == 1
    # 全 fetched_at を見る場合
    with db.get_connection() as conn:
        all_rows = conn.execute(
            "SELECT * FROM post_retention_curves WHERE post_id = ?", (p_id,),
        ).fetchall()
    assert len(all_rows) == 2


def test_query_retention_curve_returns_empty_for_unknown_post(isolated_db):
    db = isolated_db
    assert db.query_retention_curve("youtube:nope") == []


def test_query_retention_curve_specific_fetched_at(isolated_db):
    db = isolated_db
    p_id = _seed_post(db)
    db.insert_retention_curve(
        p_id,
        [{"elapsed_pct": 0.5, "ratio": 0.7}],
        fetched_at="2026-05-10T12:00:00+00:00",
    )
    db.insert_retention_curve(
        p_id,
        [{"elapsed_pct": 0.5, "ratio": 0.4}],
        fetched_at="2026-05-11T12:00:00+00:00",
    )
    older = db.query_retention_curve(p_id, fetched_at="2026-05-10T12:00:00+00:00")
    assert len(older) == 1
    assert older[0]["ratio"] == pytest.approx(0.7)


def test_insert_retention_curve_handles_empty_curve(isolated_db):
    db = isolated_db
    p_id = _seed_post(db)
    assert db.insert_retention_curve(p_id, []) == 0


def test_insert_retention_curve_orders_by_elapsed_pct(isolated_db):
    db = isolated_db
    p_id = _seed_post(db)
    db.insert_retention_curve(p_id, [
        {"elapsed_pct": 0.7, "ratio": 0.4},
        {"elapsed_pct": 0.1, "ratio": 0.95},
        {"elapsed_pct": 0.4, "ratio": 0.7},
    ])
    rows = db.query_retention_curve(p_id)
    pcts = [r["elapsed_pct"] for r in rows]
    assert pcts == sorted(pcts)
