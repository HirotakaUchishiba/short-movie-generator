#!/usr/bin/env python3
"""台本×動画×プラットフォーム成績を横断表示するStreamlitダッシュボード。

起動:
    streamlit run scripts/dashboard.py
"""
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from analytics import db

st.set_page_config(page_title="Tensyoku Movie Analytics", layout="wide")

db.init_db()


@st.cache_data(ttl=60)
def load_performance() -> pd.DataFrame:
    rows = db.query_performance()
    return pd.DataFrame(rows)


@st.cache_data(ttl=60)
def load_screenplays() -> pd.DataFrame:
    return pd.DataFrame(db.list_screenplays())


@st.cache_data(ttl=30)
def load_analyze_jobs() -> pd.DataFrame:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT j.*,
                      r.original_name AS video_name,
                      r.duration_sec AS video_duration_sec,
                      r.size_bytes   AS video_size_bytes
               FROM analyze_jobs j
               LEFT JOIN reference_videos r ON j.video_sha256 = r.sha256
               ORDER BY j.created_at DESC"""
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


@st.cache_data(ttl=30)
def load_analyze_phases() -> pd.DataFrame:
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT job_id, phase, status, duration_ms, cost_usd,
                      started_at, finished_at, error
               FROM analyze_phases"""
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def overview_tab(perf: pd.DataFrame) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("登録台本数", int(perf["screenplay_id"].nunique()) if not perf.empty else 0)
    col2.metric("生成動画数", int(perf["video_id"].nunique()) if not perf.empty else 0)
    col3.metric("投稿数", int(perf["post_id"].nunique()) if "post_id" in perf and not perf.empty else 0)
    total_views = int(perf["views"].fillna(0).sum()) if "views" in perf and not perf.empty else 0
    col4.metric("累計再生", f"{total_views:,}")

    if perf.empty:
        st.info("まだデータがありません。`scripts/ingest_screenplay.py` `scripts/ingest_video.py` `scripts/register_post.py` `scripts/fetch_metrics.py` でデータを投入してください。")
        return

    st.subheader("投稿×成績テーブル")
    show_cols = [c for c in [
        "screenplay_name", "platform", "url", "views", "likes",
        "comments", "completion_rate", "fetched_at",
    ] if c in perf.columns]
    st.dataframe(perf[show_cols].sort_values("views", ascending=False, na_position="last"),
                 use_container_width=True)


def hook_tab(perf: pd.DataFrame) -> None:
    if perf.empty or "hook_type" not in perf:
        st.info("データが不足しています")
        return
    grp = perf.dropna(subset=["hook_type"]).groupby(["hook_type", "platform"]).agg(
        n=("post_id", "count"),
        avg_views=("views", "mean"),
        avg_likes=("likes", "mean"),
        avg_completion=("completion_rate", "mean"),
    ).reset_index()

    st.subheader("フック種別 × プラットフォーム 平均成績")
    st.dataframe(grp, use_container_width=True)

    if not grp.empty:
        st.bar_chart(grp.pivot_table(index="hook_type", columns="platform", values="avg_views").fillna(0))


def emotion_tab(perf: pd.DataFrame) -> None:
    if perf.empty or "dominant_emotion" not in perf:
        st.info("データが不足しています")
        return
    grp = perf.dropna(subset=["dominant_emotion"]).groupby("dominant_emotion").agg(
        n=("post_id", "count"),
        avg_views=("views", "mean"),
        avg_completion=("completion_rate", "mean"),
    ).reset_index()
    st.subheader("支配的感情 × 平均成績")
    st.dataframe(grp, use_container_width=True)
    if not grp.empty:
        st.bar_chart(grp.set_index("dominant_emotion")[["avg_views"]])


def detail_tab(perf: pd.DataFrame, screenplays: pd.DataFrame) -> None:
    st.subheader("台本別の詳細")
    if screenplays.empty:
        st.info("台本が未登録です")
        return
    options = screenplays.apply(
        lambda r: f"{r['id']}  {r['name']}", axis=1
    ).tolist()
    selected = st.selectbox("台本を選択", options)
    if not selected:
        return
    sp_id = selected.split()[0]
    sp_row = screenplays[screenplays["id"] == sp_id].iloc[0]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### メタデータ")
        st.write({
            "name": sp_row["name"],
            "hook_type": sp_row.get("hook_type"),
            "tone": sp_row.get("tone"),
            "dominant_emotion": sp_row.get("dominant_emotion"),
            "theme": sp_row.get("theme"),
            "character_archetype": sp_row.get("character_archetype"),
            "scene_count": sp_row.get("scene_count"),
            "line_count": sp_row.get("line_count"),
            "total_duration": sp_row.get("total_duration"),
        })
    with col2:
        st.markdown("### Caption")
        st.text(sp_row.get("caption") or "")

    st.markdown("### 投稿と成績")
    my_perf = perf[perf["screenplay_id"] == sp_id]
    if my_perf.empty:
        st.info("この台本の投稿はまだありません")
    else:
        show_cols = [c for c in [
            "platform", "url", "posted_at", "views", "likes", "comments",
            "completion_rate", "avg_view_duration", "fetched_at",
        ] if c in my_perf.columns]
        st.dataframe(my_perf[show_cols], use_container_width=True)

    st.markdown("### Raw JSON")
    try:
        st.json(json.loads(sp_row["raw_json"]))
    except (json.JSONDecodeError, TypeError) as e:
        st.warning(f"raw_json の JSON パースに失敗しました: {e}")
        st.text(sp_row.get("raw_json") or "")


PHASE_ORDER = (
    "frames", "audio", "whisper", "acoustic", "claude", "save",
)


def analyze_jobs_tab(jobs: pd.DataFrame, phases: pd.DataFrame) -> None:
    if jobs.empty:
        st.info("まだ analyze ジョブはありません。"
                "UIの「参考動画から台本を生成」から実行してください。")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("総ジョブ数", len(jobs))
    col2.metric("完了", int((jobs["status"] == "completed").sum()))
    col3.metric("失敗", int((jobs["status"] == "failed").sum()))

    cost_series = jobs.get("actual_cost_usd")
    if cost_series is None:
        cost_series = pd.Series(dtype=float)
    if "estimated_cost_usd" in jobs.columns:
        cost_series = cost_series.fillna(jobs["estimated_cost_usd"])
    total_cost = float(cost_series.fillna(0).sum())
    col4.metric("累計コスト (USD)", f"${total_cost:.3f}")

    st.subheader("ジョブ一覧")
    show_cols = [c for c in [
        "id", "video_name", "status", "current_phase",
        "estimated_cost_usd", "actual_cost_usd",
        "created_at", "started_at", "finished_at", "error",
    ] if c in jobs.columns]
    st.dataframe(jobs[show_cols], use_container_width=True)

    if phases.empty:
        return

    completed_phases = phases[phases["status"] == "completed"].copy()
    if completed_phases.empty:
        return

    st.subheader("フェーズ別所要時間 (完了済みのみ)")
    stats = completed_phases.groupby("phase").agg(
        n=("duration_ms", "count"),
        mean_ms=("duration_ms", "mean"),
        median_ms=("duration_ms", "median"),
        max_ms=("duration_ms", "max"),
    ).reset_index()
    stats["order"] = stats["phase"].map(
        {p: i for i, p in enumerate(PHASE_ORDER)}
    )
    stats = stats.sort_values("order").drop(columns=["order"])
    stats["mean_sec"] = (stats["mean_ms"] / 1000).round(2)
    stats["median_sec"] = (stats["median_ms"] / 1000).round(2)
    stats["max_sec"] = (stats["max_ms"] / 1000).round(2)
    st.dataframe(
        stats[["phase", "n", "mean_sec", "median_sec", "max_sec"]],
        use_container_width=True,
    )
    chart_df = stats.set_index("phase")[["mean_sec"]]
    if not chart_df.empty:
        st.bar_chart(chart_df)

    failure_phases = phases[phases["status"] == "failed"]
    if not failure_phases.empty:
        st.subheader("失敗フェーズ")
        st.dataframe(
            failure_phases[["job_id", "phase", "error", "finished_at"]],
            use_container_width=True,
        )

    cost_data = jobs.copy()
    cost_data["effective_cost"] = (
        cost_data.get("actual_cost_usd", pd.Series(dtype=float))
        .fillna(cost_data.get("estimated_cost_usd", pd.Series(dtype=float)))
    )
    cost_data = cost_data.dropna(subset=["started_at", "effective_cost"])
    if not cost_data.empty:
        st.subheader("日別コスト推移")
        cost_data["date"] = pd.to_datetime(
            cost_data["started_at"], utc=True, errors="coerce",
        ).dt.date
        daily = cost_data.groupby("date").agg(
            cost_usd=("effective_cost", "sum"),
            jobs=("id", "count"),
        ).reset_index()
        st.line_chart(daily.set_index("date")[["cost_usd"]])


def main() -> None:
    st.title("Tensyoku Movie Analytics")

    perf = load_performance()
    screenplays = load_screenplays()
    analyze_jobs = load_analyze_jobs()
    analyze_phases = load_analyze_phases()

    tabs = st.tabs(["概要", "フック別", "感情別", "台本詳細", "分析ジョブ"])
    with tabs[0]:
        overview_tab(perf)
    with tabs[1]:
        hook_tab(perf)
    with tabs[2]:
        emotion_tab(perf)
    with tabs[3]:
        detail_tab(perf, screenplays)
    with tabs[4]:
        analyze_jobs_tab(analyze_jobs, analyze_phases)


if __name__ == "__main__":
    main()
