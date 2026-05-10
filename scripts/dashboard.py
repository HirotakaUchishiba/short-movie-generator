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
    perf_show = perf.copy()
    if "generation_cost_usd" in perf_show.columns and "views" in perf_show.columns:
        perf_show["cost_per_view_usd"] = (
            perf_show["generation_cost_usd"]
            .div(perf_show["views"].replace(0, pd.NA))
        )
    show_cols = [c for c in [
        "screenplay_name", "platform", "url", "views", "likes",
        "comments", "completion_rate", "cost_per_view_usd", "fetched_at",
    ] if c in perf_show.columns]
    st.dataframe(
        perf_show[show_cols].sort_values("views", ascending=False, na_position="last"),
        use_container_width=True,
    )


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


_STRATEGY_AXES = ("hook_type", "tone", "dominant_emotion", "theme")


def strategy_tab() -> None:
    """戦略軸別 reward を v_strategy_performance / 軸別 view から表示する。

    24h 経過後の metrics のみ採用するノイズ排除済 reward (= v_*_performance の
    julianday filter) を読むので、自前 groupby より早期段階の歪みが少ない。
    strategy フィルタで baseline / shadow / active を切り替えて A/B を見る。
    """
    metric = st.selectbox(
        "metric", ["avg_completion", "avg_views", "avg_save"],
        key="strategy_metric",
    )
    strategy = st.selectbox(
        "strategy", [None, "baseline", "shadow", "active"],
        format_func=lambda v: v or "all",
        key="strategy_filter",
    )
    any_data = False
    for axis in _STRATEGY_AXES:
        try:
            rows = db.query_axis_performance(
                axis, metric=metric, strategy_prefix=strategy,
            )
        except Exception as e:
            st.warning(f"{axis}: 取得失敗 ({e})")
            continue
        if not rows:
            continue
        any_data = True
        df = pd.DataFrame(rows)
        st.subheader(f"{axis} × {metric}")
        st.dataframe(df, use_container_width=True)
        if not df.empty:
            st.bar_chart(df.set_index("axis_value")["metric"])
    if not any_data:
        st.info(
            "投稿後 24h 以上経過した metrics が必要です。"
            "scripts/fetch_metrics.py で取得後、時間を置いて再表示してください。"
        )


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
    my_perf = perf[perf["screenplay_id"] == sp_id].copy()
    if my_perf.empty:
        st.info("この台本の投稿はまだありません")
    else:
        if "generation_cost_usd" in my_perf.columns and "views" in my_perf.columns:
            my_perf["cost_per_view_usd"] = (
                my_perf["generation_cost_usd"]
                .div(my_perf["views"].replace(0, pd.NA))
            )
        show_cols = [c for c in [
            "platform", "url", "posted_at", "views", "likes", "comments",
            "completion_rate", "avg_view_duration",
            "cost_per_view_usd", "fetched_at",
        ] if c in my_perf.columns]
        st.dataframe(my_perf[show_cols], use_container_width=True)

        post_options: list[str] = []
        for _, row in my_perf.iterrows():
            pid = row.get("post_id")
            if pid:
                platform = row.get("platform") or "?"
                post_options.append(f"{pid}  ({platform})")
        if post_options:
            st.markdown("### 投稿後の伸び (= 時系列)")
            selected_post = st.selectbox(
                "post を選択", post_options, key=f"detail_post_{sp_id}",
            )
            if selected_post:
                post_id = selected_post.split()[0]
                series = db.query_post_metrics_timeseries(post_id)
                if series:
                    ts_df = pd.DataFrame(series)
                    ts_df["fetched_at"] = pd.to_datetime(
                        ts_df["fetched_at"], utc=True, errors="coerce",
                    )
                    ts_df = ts_df.dropna(subset=["fetched_at"]).sort_values("fetched_at")
                    chart_cols = [c for c in [
                        "views", "likes", "comments", "completion_rate",
                    ] if c in ts_df.columns]
                    if chart_cols and not ts_df.empty:
                        st.line_chart(ts_df.set_index("fetched_at")[chart_cols])
                    else:
                        st.info("時系列に表示可能な数値カラムがありません。")
                else:
                    st.info("post_metrics の時系列データがありません。"
                            "scripts/fetch_metrics.py を複数回実行すると蓄積されます。")

    st.markdown("### Raw JSON")
    try:
        st.json(json.loads(sp_row["raw_json"]))
    except Exception:
        st.text(sp_row.get("raw_json") or "")


def experiments_tab() -> None:
    """experiment_assignments の試行履歴と軸 × strategy 集計を表示する。"""
    rows = db.list_experiment_assignments(limit=500)
    if not rows:
        st.info(
            "experiment_assignments が空です。"
            "Phase 3 closed-loop が走り始めると蓄積されます。"
        )
        return
    df = pd.DataFrame(rows)

    st.subheader("軸 × strategy の試行回数")
    if {"axis", "strategy"}.issubset(df.columns):
        pivot = df.groupby(["axis", "strategy"]).size().unstack(fill_value=0)
        st.dataframe(pivot, use_container_width=True)

    st.subheader("直近 200 件の履歴")
    show_cols = [c for c in [
        "id", "video_id", "axis", "selected_value", "strategy",
        "observed_value", "scene_idx", "composition_id", "created_at",
    ] if c in df.columns]
    st.dataframe(df[show_cols].head(200), use_container_width=True)


def quality_tab() -> None:
    """qa_failures の stage 別件数 + generation_records.validator_scores 推移。"""
    qa_rows = db.list_qa_failures(limit=500)
    st.subheader("QA 失敗サマリ (= 直近 500 件)")
    if qa_rows:
        qa_df = pd.DataFrame(qa_rows)
        if {"stage", "source"}.issubset(qa_df.columns):
            agg = qa_df.groupby(["stage", "source"]).size().unstack(fill_value=0)
            st.dataframe(agg, use_container_width=True)
        st.markdown("#### 直近の QA 失敗")
        show_cols = [c for c in [
            "id", "ts", "stage", "scene_idx", "source", "tags",
            "note", "artifact_path", "created_at",
        ] if c in qa_df.columns]
        st.dataframe(qa_df[show_cols].head(50), use_container_width=True)
    else:
        st.info("qa_failures が空です。")

    st.subheader("validator_scores 推移 (= generation_records)")
    gen_rows = db.list_generation_records(limit=200)
    score_rows: list[dict] = []
    for rec in gen_rows:
        scores = rec.get("validator_scores")
        if not isinstance(scores, dict):
            continue
        flat: dict = {"ts": rec.get("ts"), "created_at": rec.get("created_at")}
        for k, v in scores.items():
            if isinstance(v, (int, float)):
                flat[k] = v
        if len(flat) > 2:
            score_rows.append(flat)
    if score_rows:
        score_df = pd.DataFrame(score_rows)
        score_df["created_at"] = pd.to_datetime(
            score_df["created_at"], utc=True, errors="coerce",
        )
        score_df = score_df.dropna(subset=["created_at"]).sort_values("created_at")
        numeric_cols = [c for c in score_df.columns
                        if c not in ("ts", "created_at")]
        if numeric_cols and not score_df.empty:
            st.line_chart(score_df.set_index("created_at")[numeric_cols])
        st.dataframe(score_df.tail(50), use_container_width=True)
    else:
        st.info(
            "generation_records.validator_scores が空または数値スコアを含みません。"
        )


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

    tabs = st.tabs([
        "概要", "戦略軸", "フック別", "感情別",
        "実験", "品質", "台本詳細", "分析ジョブ",
    ])
    with tabs[0]:
        overview_tab(perf)
    with tabs[1]:
        strategy_tab()
    with tabs[2]:
        hook_tab(perf)
    with tabs[3]:
        emotion_tab(perf)
    with tabs[4]:
        experiments_tab()
    with tabs[5]:
        quality_tab()
    with tabs[6]:
        detail_tab(perf, screenplays)
    with tabs[7]:
        analyze_jobs_tab(analyze_jobs, analyze_phases)


if __name__ == "__main__":
    main()
