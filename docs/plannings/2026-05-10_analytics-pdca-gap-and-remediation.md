# Analytics PDCA Gap Audit + Remediation Plan

**date**: 2026-05-10 / **base branch**: `main` / **status**: 🔴 重要 — dashboard と DB の双方に PDCA 必須 KPI の欠落

`docs/content-strategy.md` (= 動画戦略の根本) は **「アイデア > パッケージ > スクリプト > 撮影 > 編集」のピラミッドで上流に 80% の労力を割き、当たった動画を MVP step ごとに分析して再現する** ことを PDCA の中核に据えている。

しかし現状、

- **DB スキーマ**は PDCA を回す前提で整備されている (= `experiment_assignments`, `v_strategy_performance`, 軸別 view, `qa_failures`, `generation_records.validator_scores`) が、
- **Streamlit dashboard** はそのうち `v_performance` (= 全期間混合) と `analyze_jobs` だけしか参照しておらず、PDCA の Check に必要な視点を半分以上素通りしている。
- さらに **戦略書が最重要視する CTR / 30 秒地点 retention / impressions** は DB カラムにも fetch コードにも存在しない。

本 doc は **設計 (= content-strategy + analytics schema) と実装 (= fetch_metrics + dashboard) のギャップを正直に列挙し、完全準拠までの修正計画を Phase 別に提示する** ことを目的とする。

---

## TL;DR

- **準拠度**: 約 30%。DB スキーマは P0 軸まで揃っているが、UI が未配線。中核 3 KPI (CTR / 30秒 retention / impressions) は DB / fetch 双方で未装備
- **本質**: 「**スキーマ設計者が想定した PDCA Loop と、可視化レイヤが提供している view が解離している**」 → 設計上の意図 (= 軸別 reward / strategy 別 reward / 24h ノイズ排除) が UI に届いていない
- **修正範囲**: Phase A (= UI を既存 DB に追従) → Phase B (= 中核 KPI の fetch + 保存) → Phase C (= 戦略の概念モデルを DB に表現) の 3 段
- **見積り**: Phase A は 1〜2 日、Phase B は 3〜5 日、Phase C は 1〜2 週

---

## 1. 設計の正と現状実装の mismatch 全列挙

優先度: 🔴 **戦略の中核に直結 / 即修正** / 🟠 **資産が遊んでいる / 短期修正** / 🟡 **将来の拡張余地**

### 🔴 1-1: dashboard が `v_strategy_performance` を完全未参照

| 項目         | 内容                                                                                                                                                                                                                                           |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ❌ 未準拠                                                                                                                                                                                                                                      |
| 設計上の役割 | `analytics/schema.sql:310-326` の view。`experiment_assignments.strategy` (= `baseline` / `shadow_explore` / `shadow_exploit` / `active_explore` / `active_exploit`) 別に reward を分離する。bandit の reward source として **A/B 検証の正本** |
| 証拠         | `grep -n "v_strategy_performance" scripts/dashboard.py` → 0 件。`analytics/db.py:662` の `query_axis_performance(strategy_prefix=...)` も dashboard から呼ばれない                                                                             |
| 影響         | 戦略軸 (hook_type / tone / dominant_emotion / theme) ごとに「baseline → shadow → active」の伸びを追えない。**PDCA の Act フェーズで何を選んで投入すればよいか判断できない**                                                                    |
| 修正先       | `scripts/dashboard.py` に「戦略軸」タブを追加し、`db.query_axis_performance(axis, strategy_prefix=...)` を 4 軸 × 3 strategy で表示                                                                                                            |

### 🔴 1-2: dashboard が軸別 view (24h フィルタ済) を使わず自前 groupby で代用

| 項目         | 内容                                                                                                                                                                                                                |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ❌ 未準拠 (= ノイズが混入)                                                                                                                                                                                          |
| 設計上の役割 | `v_hook_type_performance` / `v_tone_performance` / `v_dominant_emotion_performance` / `v_theme_performance` (= `analytics/schema.sql:234-300`) は **投稿後 24h 経過した metrics のみ** を採用してノイズ排除する設計 |
| 証拠         | `dashboard.py:87-91, 105-108` で `perf` (= `v_performance`、24h フィルタ無し) を pandas で groupby しているだけ                                                                                                     |
| 影響         | **投稿直後でまだ伸びていない動画**もそのまま平均に混ぜている → 軸別の reward が早期段階で歪む                                                                                                                       |
| 修正先       | `dashboard.py` の `hook_tab` / `emotion_tab` を、`db.query_axis_performance(axis)` 経由 (= 軸別 view 直読み) に置換                                                                                                 |

### 🔴 1-3: CTR (= サムネ + タイトルの強さ) が DB / fetch 双方で未装備

| 項目         | 内容                                                                                                                                                                                                   |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 状態         | ❌ 未準拠                                                                                                                                                                                              |
| 設計上の役割 | content-strategy.md L52-58, L191-200 が示す **80/20 ルールの中核**: 「クリックされなければ全て無駄。アイデア + パッケージに 80% を投資せよ」                                                           |
| 証拠         | `post_metrics.ctr` カラムは存在 (= `schema.sql:85`) するが `youtube.fetch_analytics` (= `platform_clients/youtube.py:276-318`) で `cardImpressions` / `impressionClickThroughRate` を query していない |
| 影響         | サムネ + タイトル品質を **どう改善すべきかの数値根拠が無い**。フックが効いていないのか、そもそもクリックされていないのかを切り分けられない                                                             |
| 修正先       | `youtube.fetch_analytics` の metrics に `cardImpressions,cardClickRate` (= Cards CTR) と Reports API の `impressions,impressionsClickThroughRate` を追加 + `post_metrics.ctr` に書き込み               |

### 🔴 1-4: 30 秒地点 retention (= フックの強さ) が DB / fetch 双方で未装備

| 項目         | 内容                                                                                                                                                                                 |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 状態         | ❌ 未準拠                                                                                                                                                                            |
| 設計上の役割 | content-strategy.md L57, L242-247: **「30 秒で 50% が離脱する。フックに最大の労力を割け」** — 動画の最重要 KPI                                                                       |
| 証拠         | YouTube Analytics の `audienceWatchRatio` (= elapsed % vs 視聴維持率) を fetch していない。`post_metrics` も time-series retention を保存する構造になっていない                      |
| 影響         | **フックが効いているかどうかが永久に分からない**。完遂率 (`completion_rate`) は単一値で、30 秒地点での drop を分離できない                                                           |
| 修正先       | (a) `post_retention_curves` テーブルを新設し `(post_id, fetched_at, elapsed_pct, ratio)` で保存。(b) `youtube.fetch_analytics` に dimension `elapsedVideoTimeRatio` で取得経路を追加 |

### 🔴 1-5: impressions / traffic_source が DB / fetch 双方で未装備

| 項目         | 内容                                                                                                                                                                                               |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ❌ 未準拠                                                                                                                                                                                          |
| 設計上の役割 | content-strategy.md L78-98: アルゴリズム適合は **「impressions → click → watch → engagement」 の funnel で測る**。impression すらされていない動画と、impression は出るがクリックされない動画は別物 |
| 証拠         | YouTube Analytics の `insightTrafficSourceType` dimension / `impressions` metric は fetch コード上に存在しない (= `grep -rn "impressions\|insightTrafficSourceType"` → 0 件)                       |
| 影響         | 「アルゴリズムに配信されていない (= impressions が出ていない)」と「配信はされているがクリックされていない (= CTR が低い)」を切り分けられない → **PDCA の打ち手が決まらない**                       |
| 修正先       | `post_metrics` に `impressions` / `traffic_browse_pct` / `traffic_suggested_pct` / `traffic_search_pct` / `traffic_external_pct` を追加 + `fetch_analytics` で取得                                 |

### 🟠 1-6: `subscribersGained` を query しているのに return から落としている

| 項目         | 内容                                                                                                                                 |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| 状態         | ❌ 未準拠 (= 1 行で直る)                                                                                                             |
| 設計上の役割 | content-strategy.md L277-283 の **Halo effect** (= 1 本のヒットがチャンネル全体に波及する) を測る上でのプロキシ                      |
| 証拠         | `platform_clients/youtube.py:276-280` で `subscribersGained` を metrics に含めているのに、L309-318 の return dict には含まれていない |
| 影響         | チャンネル成長への寄与度が動画別に分からない                                                                                         |
| 修正先       | `youtube.fetch_analytics` の return に `subscribers_gained` キーを追加。`post_metrics` カラムも追加                                  |

### 🟠 1-7: `experiment_assignments` / `qa_failures` / `generation_records` を dashboard が完全未参照

| 項目         | 内容                                                                                                                                                                                                        |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ❌ 未準拠                                                                                                                                                                                                   |
| 設計上の役割 | (a) `experiment_assignments` = 軸ごとの試行履歴 (Phase 3 closed-loop の中核)、(b) `qa_failures` = UI reject + regenerate された不良サンプル台帳、(c) `generation_records.validator_scores` = 自動 QA の趨勢 |
| 証拠         | `grep -n "experiment_assignments\|qa_failures\|generation_records" scripts/dashboard.py` → 0 件                                                                                                             |
| 影響         | 「(a) どの軸がどれだけ試行されたか / (b) どの stage で QA NG が多いか / (c) validator score が下がっていないか」のいずれも UI で見えない                                                                    |
| 修正先       | dashboard に「実験」「品質」 2 タブを新設                                                                                                                                                                   |

### 🟠 1-8: post_metrics 時系列推移グラフが無い

| 項目         | 内容                                                                                                                                                                                                 |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ❌ 未準拠                                                                                                                                                                                            |
| 設計上の役割 | content-strategy.md L257-271: 「**1 本でも当たったら止まって、なぜ当たったかを MVP step で分析せよ**」 → 投稿直後の伸び方が肝                                                                        |
| 証拠         | `post_metrics` テーブルは `(post_id, fetched_at)` で時系列に積まれている (= `schema.sql:73-90`) のに、dashboard の `detail_tab` (`dashboard.py:148-157`) は最新値だけ表示する `v_performance` を読む |
| 影響         | **投稿後 1h / 24h / 7day の伸びの "曲線" が見えない** → 当たり動画の判別が遅れる                                                                                                                     |
| 修正先       | `detail_tab` に `(fetched_at vs views/likes/completion_rate)` の line chart を追加                                                                                                                   |

### 🟠 1-9: ROI (= cost_per_view, cost_per_subscriber) ビューが無い

| 項目         | 内容                                                                                                                                                                            |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ❌ 未準拠                                                                                                                                                                       |
| 設計上の役割 | architecture-decisions.md §5 「コスト構造」 と CLAUDE.md 「コストのかかる操作を安易に実行しない」が示す **製造コスト管理** + content-strategy.md の「データドリブン」を結ぶ KPI |
| 証拠         | `videos.generation_cost_usd` (= `schema.sql:40`) は保存されているが、dashboard では未参照 (= `grep -n "generation_cost_usd" scripts/dashboard.py` → 0 件)                       |
| 影響         | **1 本いくらかけて何 view 取れたかが分からない** → コスト最適化の判断材料がない                                                                                                 |
| 修正先       | `v_performance` に `generation_cost_usd / NULLIF(views, 0)` 等の computed 列を追加し、dashboard 概要タブと detail_tab で表示                                                    |

### 🟡 1-10: Halo effect (= 1 本ヒット時の過去動画への波及) を測る view が無い

| 項目         | 内容                                                                                                                                            |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ❌ 未準拠                                                                                                                                       |
| 設計上の役割 | content-strategy.md L277-283 の Halo effect は **戦略書の中で「Transformation の一貫性」を支える根幹的な観察**                                  |
| 証拠         | 「1 本ヒット時刻を基準に、同 transformation の過去動画 metrics の delta」を計算する view も query も存在しない                                  |
| 影響         | 「Transformation 軸の一貫性が活きているか」を経験ではなくデータで判断できない                                                                   |
| 修正先       | (Phase C) `v_halo_effect` view を新設。最低 1 本の outlier (= avg + 3σ) を起点に、その投稿前後 7 日で同 `theme` の他 post の views delta を計算 |

### 🟡 1-11: Tree main_branch / transformation / POV が screenplays スキーマに無い

| 項目         | 内容                                                                                                                                                                                        |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ❌ 未準拠                                                                                                                                                                                   |
| 設計上の役割 | content-strategy.md Phase 1 (= L78-167) の中核概念。**Transformation = 視聴者にもたらす変化、Tree = 4 つの主要課題、POV = 独自視点**。すべての PDCA は「同じ transformation か」 を軸に回す |
| 証拠         | `screenplays` テーブルには `theme` (flat 文字列) しかなく、`transformation` / `tree_main_branch` / `pov_id` が無い                                                                          |
| 影響         | (a) Halo effect の計算ができない、(b) Tree 4 branch の偏りが見えない、(c) POV の戦略上の差別化を測れない                                                                                    |
| 修正先       | (Phase C) `screenplays` に列追加 + auto_tag に Claude が `transformation` / `tree_main_branch` を抽出する pass を追加                                                                       |

### 🟡 1-12: dashboard が `v_active_posts` を経由せず rollback 済 post も平均に混ぜている

| 項目         | 内容                                                                                                                                     |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 状態         | ⚠️ 部分準拠 (= `v_strategy_performance` 経由なら自動除外されるが、`v_performance` は混ぜる)                                              |
| 設計上の役割 | `v_active_posts` (= `schema.sql:67-71`) は schema v9 で追加された **取り下げ post を analytics から除外する仕組み**                      |
| 証拠         | `v_performance` (= `schema.sql:329-355`) は posts テーブル直接 join (= `LEFT JOIN posts p ON ...`) で `rollback_at IS NULL` フィルタ無し |
| 影響         | rollback 済 post の (= 削除されたであろう低評価動画) metrics も平均に混ざる                                                              |
| 修正先       | `v_performance` の `LEFT JOIN posts` を `LEFT JOIN v_active_posts` に置き換え                                                            |

### 補足: Instagram / TikTok の retention は API 側に存在しない

| 項目   | 内容                                                                                                                                                  |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| 状態   | ⚠️ プラットフォーム制約                                                                                                                               |
| 証拠   | `platform_clients/instagram.py:33-65` の Insights API は `reach,plays,likes,comments,saved,shares,total_interactions` のみ。retention は API で出ない |
| 影響   | IG / TikTok では 30 秒地点 retention が原理的に取れない (= API 仕様)                                                                                  |
| 緩和策 | `scripts/ingest_tiktok_csv.py` のように **TikTok Studio CSV** / **IG プロアカウント手動エクスポート** を取り込む経路は既存 (= 手動 import が現実解)   |

---

## 2. 修正方針 (= Phase 別)

設計準拠への 3 Phase。**Phase A は既存資産の wire 不足を埋めるだけ** なので、最初に着手して効果を確認してから Phase B / C に進むのが妥当。

### Phase A: UI を既存 DB に追従させる (= 1〜2 日)

**狙い**: スキーマには既にある PDCA 用 view / table を、Streamlit に出すだけ。AI 課金 0 / 新規 fetch 0 / マイグレーション無し。

#### A-1: dashboard.py に「戦略軸」タブを追加

`db.query_axis_performance(axis, strategy_prefix=None)` を 4 軸 × { all / baseline / shadow / active } で表示。

```python
# scripts/dashboard.py に追加
def strategy_tab() -> None:
    axes = ["hook_type", "tone", "dominant_emotion", "theme"]
    metric = st.selectbox("metric", ["avg_completion", "avg_views", "avg_save"])
    strategy = st.selectbox("strategy", [None, "baseline", "shadow", "active"],
                             format_func=lambda v: v or "all")
    for axis in axes:
        rows = db.query_axis_performance(axis, metric=metric, strategy_prefix=strategy)
        if not rows:
            continue
        df = pd.DataFrame(rows)
        st.subheader(f"{axis} × {metric}")
        st.dataframe(df, use_container_width=True)
        st.bar_chart(df.set_index("axis_value")["metric"])
```

**受入基準**: `experiment_assignments` に試行データがある状態で、軸別 reward が `baseline` と `active` で違いを出せる。

#### A-2: dashboard.py に「実験」タブ (= experiment_assignments)

`db.list_experiment_assignments(limit=200)` で試行履歴を直近順に表示。 `axis × selected_value × strategy × observed_value × scene_idx × composition_id` の生履歴 + axis × strategy 別の試行回数 heatmap。

**受入基準**: 「最近 30 日でどの軸を何回試したか」が一目で分かる。

#### A-3: dashboard.py に「品質」タブ (= qa_failures + validator_scores)

(a) `db.list_qa_failures(stage=None, limit=200)` で stage / source 別の集計 + 直近サンプル一覧、(b) `generation_records.validator_scores` (= JSON) を時系列に展開して line chart。

**受入基準**: 「最近 7 日で QA NG が増えた stage はどれか」「validator スコアが下がっていないか」が見える。

#### A-4: detail_tab に時系列推移 + ROI を追加

(a) `post_metrics` を `(fetched_at, views/likes/completion_rate)` で時系列展開し line chart、(b) `views / generation_cost_usd` を「cost_per_view」 として表示。

**affected files**: `scripts/dashboard.py`、`analytics/db.py` (= `query_post_metrics_timeseries(post_id)` 関数を新設)。

**受入基準**: 1 台本を選ぶと「投稿後の伸び」と「1 view あたりのコスト」が見える。

#### A-5: `v_performance` を `v_active_posts` 経由に修正

```sql
-- analytics/schema.sql の v_performance 定義変更
CREATE VIEW IF NOT EXISTS v_performance AS
SELECT ...
FROM screenplays s
JOIN videos v ON v.screenplay_id = s.id
LEFT JOIN v_active_posts p ON p.video_id = v.id  -- ← posts → v_active_posts に変更
LEFT JOIN v_latest_metrics m ON m.post_id = p.id;
```

migration: `analytics/db.py:48 init_db()` で `DROP VIEW IF EXISTS v_performance` を追加し、schema.sql の `CREATE VIEW IF NOT EXISTS` で再生成。

**受入基準**: rollback 済 post が概要タブの集計から消える。

---

### Phase B: 戦略書中核 KPI を fetch + DB 保存 (= 3〜5 日)

**狙い**: Phase A の UI が出揃った段階で、**戦略書が最重要視する CTR / 30秒 retention / impressions / subscribersGained** を fetch して見える化する。スキーマ migration が必要。

#### B-1: schema migration (= `post_metrics` カラム追加 + 新テーブル)

```sql
-- post_metrics に追加 (= ALTER TABLE で additive)
ALTER TABLE post_metrics ADD COLUMN impressions INTEGER;
ALTER TABLE post_metrics ADD COLUMN subscribers_gained INTEGER;
ALTER TABLE post_metrics ADD COLUMN traffic_browse_pct REAL;
ALTER TABLE post_metrics ADD COLUMN traffic_suggested_pct REAL;
ALTER TABLE post_metrics ADD COLUMN traffic_search_pct REAL;
ALTER TABLE post_metrics ADD COLUMN traffic_external_pct REAL;
-- 既存 post_metrics.ctr は impressions / clicks から導出 (= スキーマ変更不要)

-- 30 秒地点 retention のための新テーブル
CREATE TABLE IF NOT EXISTS post_retention_curves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    fetched_at TEXT NOT NULL,
    elapsed_pct REAL NOT NULL,    -- 0.0〜1.0、動画進行率
    elapsed_sec REAL,             -- post.video_duration から計算可能
    ratio REAL NOT NULL,          -- 維持率 (= 1.0 = 全員残ってる)
    raw_response TEXT,
    UNIQUE(post_id, fetched_at, elapsed_pct)
);

CREATE INDEX IF NOT EXISTS idx_retention_post_time
ON post_retention_curves(post_id, fetched_at);
```

`analytics/db.py:CURRENT_SCHEMA_VERSION` を `9 → 10` に上げ、`init_db()` の `_ensure_column` 経路で additive migration。

**affected files**: `analytics/schema.sql`, `analytics/db.py`.

#### B-2: `youtube.fetch_analytics` 拡張

```python
# platform_clients/youtube.py:fetch_analytics の metrics に追加
metrics = ",".join([
    "views", "likes", "comments", "shares",
    "averageViewDuration", "averageViewPercentage",
    "estimatedMinutesWatched", "subscribersGained",
    "impressions",                     # ← 新規
    "impressionsClickThroughRate",     # ← 新規 (= CTR)
])

# return に追加
return {
    ...,
    "impressions": int(m.get("impressions", 0) or 0),
    "ctr": float(m.get("impressionsClickThroughRate", 0) or 0) / 100.0,
    "subscribers_gained": int(m.get("subscribersGained", 0) or 0),  # ← 既存 query を拾う
    ...
}
```

#### B-3: `youtube.fetch_traffic_sources` (新関数)

YouTube Analytics の **dimension `insightTrafficSourceType`** を別 API call で取り、上位 4 categories (`YT_BROWSE`, `RELATED_VIDEO`, `YT_SEARCH`, `EXT_URL`) の views シェアを percent で算出。`post_metrics.traffic_*_pct` に書き込む。

#### B-4: `youtube.fetch_retention_curve` (新関数)

YouTube Analytics の **dimension `elapsedVideoTimeRatio`** で動画内の各時点の `audienceWatchRatio` を取得。`post_retention_curves` に行を bulk insert。

```python
def fetch_retention_curve(video_id: str) -> list[dict]:
    """elapsedVideoTimeRatio dimension で 0.0〜1.0 の retention 曲線を取得。"""
    # ... oauth ...
    resp = requests.get(
        f"{ANALYTICS_API_BASE}/reports",
        params={
            "ids": "channel==MINE",
            "dimensions": "elapsedVideoTimeRatio",
            "metrics": "audienceWatchRatio,relativeRetentionPerformance",
            "filters": f"video=={video_id}",
            "startDate": ...,
            "endDate": ...,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # rows = [(elapsed_ratio, watch_ratio, relative_perf), ...]
    return [{"elapsed_pct": e, "ratio": w} for (e, w, _) in resp.json().get("rows", [])]
```

#### B-5: `fetch_metrics.py` 経路で B-2 / B-3 / B-4 を駆動

`fetch_metrics_for_post(post)` を YouTube については以下の合成にする:

```python
# platform_clients/youtube.py
def fetch_metrics_for_post(post: dict) -> dict:
    video_id = post["platform_post_id"]
    result = {}

    # 既存 (Analytics API + Data API) はそのまま
    try: result.update(fetch_analytics(video_id))
    except Exception as e: logger.info(...)
    try:
        for k, v in fetch_public_stats(video_id).items():
            result.setdefault(k, v)
    except Exception as e: logger.warning(...)

    # 新規: traffic source breakdown
    try: result.update(fetch_traffic_sources(video_id))
    except Exception as e: logger.info(...)

    # 新規: retention curve は post_metrics ではなく専用テーブルへ
    try:
        curve = fetch_retention_curve(video_id)
        result["_retention_curve"] = curve   # underscore prefix で db.insert_metrics は無視
    except Exception as e: logger.info(...)

    return result
```

`scripts/fetch_metrics.py` に retention curve 専用の insert 経路を追加 (= `db.insert_retention_curve(post_id, curve)`)。

#### B-6: dashboard で 30 秒地点 retention を表示

`detail_tab` に追加:

```python
# 直近 fetch の retention curve を取得して line chart
curve = db.query_retention_curve(post_id)
if curve:
    df = pd.DataFrame(curve)
    df["elapsed_sec"] = df["elapsed_pct"] * post["video_duration_sec"]
    st.line_chart(df.set_index("elapsed_sec")["ratio"])
    # 30 秒地点
    if post["video_duration_sec"] >= 30:
        ratio_at_30 = ...
        st.metric("30 秒時点 retention", f"{ratio_at_30:.0%}")
```

**affected files**: `scripts/dashboard.py`, `analytics/db.py`, `platform_clients/youtube.py`.

**受入基準**:

- (a) 投稿動画 1 本に対して 30 秒地点の retention が出る
- (b) CTR / impressions / traffic_source_pct が概要タブに見える
- (c) `subscribers_gained` が detail_tab で見える

---

### Phase C: 戦略の概念モデルを DB に表現 (= 1〜2 週)

**狙い**: content-strategy.md Phase 1 の **Transformation / Tree / POV** をスキーマに刻む。これにより Halo effect 計測が可能になり、**「Transformation 軸の一貫性」が経験ではなくデータで判定できる** ようになる。

#### C-1: `screenplays` に概念列を追加

```sql
ALTER TABLE screenplays ADD COLUMN transformation TEXT;        -- 例: "寿司屋オーナーが客を増やせるようになる"
ALTER TABLE screenplays ADD COLUMN tree_main_branch TEXT;      -- 例: "get_more_customers" (= 4 主要課題のいずれか)
ALTER TABLE screenplays ADD COLUMN pov_id TEXT;                -- 例: "hustle" / "lifestyle" / "data_driven"

CREATE INDEX IF NOT EXISTS idx_screenplays_transformation ON screenplays(transformation);
CREATE INDEX IF NOT EXISTS idx_screenplays_branch ON screenplays(tree_main_branch);

-- transformation × branch 単位の集計 view
CREATE VIEW IF NOT EXISTS v_transformation_performance AS
SELECT
    s.transformation, s.tree_main_branch,
    COUNT(*) AS n,
    AVG(m.views) AS avg_views,
    AVG(m.completion_rate) AS avg_completion,
    SUM(m.subscribers_gained) AS sum_subs_gained
FROM screenplays s
JOIN videos v ON v.screenplay_id = s.id
JOIN v_active_posts p ON p.video_id = v.id
LEFT JOIN v_latest_metrics m ON m.post_id = p.id
WHERE m.fetched_at IS NOT NULL
  AND p.posted_at IS NOT NULL
  AND julianday(m.fetched_at) - julianday(p.posted_at) >= 1.0
GROUP BY s.transformation, s.tree_main_branch;
```

#### C-2: auto_tag (= Claude Haiku) に concept extraction pass を追加

`scripts/ingest_screenplay.py` の auto_tag prompt に以下を追加:

```
以下の出力フィールドも抽出せよ:
- transformation: 視聴者にもたらすスキル or 信念の変化を 1 文で
- tree_main_branch: 4 つの根のいずれか (= e.g. ["問題発見", "実装解説", "失敗事例共有", "ツール紹介"])
- pov_id: クリエイターの POV ラベル (= 既存の pov_id 集合から、無ければ新規提案)
```

prompt は **`config/transformation_taxonomy.yaml`** で運用者管理する (= 単価カタログと同じ運用思想で、Claude にハードコードしない)。

#### C-3: Halo effect view

```sql
CREATE VIEW IF NOT EXISTS v_halo_effect AS
WITH outliers AS (
    -- avg + 3σ を超えた views のヒット動画 (= 起点)
    SELECT s.id AS sp_id, s.transformation, p.id AS post_id, p.posted_at, m.views
    FROM screenplays s
    JOIN videos v ON v.screenplay_id = s.id
    JOIN v_active_posts p ON p.video_id = v.id
    JOIN v_latest_metrics m ON m.post_id = p.id
    WHERE m.views > (SELECT AVG(views) + 3 * (-- stdev approx --)
                     FROM v_latest_metrics)
)
SELECT
    o.transformation,
    o.post_id AS hit_post_id,
    o.posted_at AS hit_at,
    AVG(m2.views) AS avg_views_post_hit,        -- ヒット後 7 日の同 transformation views
    AVG(m1.views) AS avg_views_pre_hit          -- ヒット前 7 日の同 transformation views
FROM outliers o
JOIN screenplays s2 ON s2.transformation = o.transformation
JOIN videos v2 ON v2.screenplay_id = s2.id
JOIN v_active_posts p2 ON p2.video_id = v2.id AND p2.id != o.post_id
LEFT JOIN v_latest_metrics m1 ON m1.post_id = p2.id
    AND julianday(m1.fetched_at) BETWEEN julianday(o.hit_at) - 7 AND julianday(o.hit_at)
LEFT JOIN v_latest_metrics m2 ON m2.post_id = p2.id
    AND julianday(m2.fetched_at) BETWEEN julianday(o.hit_at) AND julianday(o.hit_at) + 7
GROUP BY o.transformation, o.post_id, o.posted_at;
```

dashboard に「Halo effect」タブを追加し、ヒット動画を起点に同 transformation の他動画 views の delta を出す。

#### C-4: dashboard 概要タブを transformation × tree_main_branch 視点に再編

「フック別」「感情別」タブの上位概念として「Transformation / Branch 別」 を追加。content-strategy.md の Phase 1 が示した戦略レベルの集計を最上位に据える。

**affected files**: `analytics/schema.sql`, `analytics/db.py`, `scripts/ingest_screenplay.py`, `scripts/dashboard.py`, **新設** `config/transformation_taxonomy.yaml`.

**受入基準**:

- (a) 1 台本に transformation / tree_main_branch / pov_id が auto_tag される
- (b) Halo effect view で「ヒット動画の前後 7 日で同 transformation の他動画の views が伸びたか」を判定できる
- (c) dashboard 最上位タブが Transformation 視点

---

## 3. スキーマ変更の詳細 (= consolidated migration)

Phase B / C で追加される列・テーブルの完全な migration を下記にまとめる。**`analytics/db.py:48 init_db()` の `_ensure_column` 経路 + `DROP VIEW IF EXISTS` 経路で additive migration** を行い、既存データは破壊しない。

```sql
-- schema v10: PDCA 中核 KPI 対応
ALTER TABLE post_metrics  ADD COLUMN impressions INTEGER;
ALTER TABLE post_metrics  ADD COLUMN subscribers_gained INTEGER;
ALTER TABLE post_metrics  ADD COLUMN traffic_browse_pct REAL;
ALTER TABLE post_metrics  ADD COLUMN traffic_suggested_pct REAL;
ALTER TABLE post_metrics  ADD COLUMN traffic_search_pct REAL;
ALTER TABLE post_metrics  ADD COLUMN traffic_external_pct REAL;

CREATE TABLE IF NOT EXISTS post_retention_curves (...);

-- schema v11: 戦略概念モデル
ALTER TABLE screenplays   ADD COLUMN transformation TEXT;
ALTER TABLE screenplays   ADD COLUMN tree_main_branch TEXT;
ALTER TABLE screenplays   ADD COLUMN pov_id TEXT;

CREATE VIEW IF NOT EXISTS v_transformation_performance AS ...;
CREATE VIEW IF NOT EXISTS v_halo_effect AS ...;

-- schema v10/v11 共通: v_performance を v_active_posts 経由に
DROP VIEW IF EXISTS v_performance;
CREATE VIEW v_performance AS
    SELECT ...
    FROM screenplays s
    JOIN videos v ON v.screenplay_id = s.id
    LEFT JOIN v_active_posts p ON p.video_id = v.id    -- 修正点
    LEFT JOIN v_latest_metrics m ON m.post_id = p.id;
```

`CURRENT_SCHEMA_VERSION` の遷移: `9 → 10 (Phase B 完了時) → 11 (Phase C 完了時)`。

---

## 4. 受入基準 (= Definition of Done)

各 Phase の完了判定。**全項目が ✅ になるまで次 Phase に進まない。**

### Phase A 完了条件

- [ ] `dashboard.py` に「戦略軸」「実験」「品質」 3 タブが存在する
- [ ] 「戦略軸」タブで `strategy = active` を選ぶと `v_strategy_performance` 経由の reward が出る
- [ ] 「品質」タブで `qa_failures` の stage 別件数と `validator_scores` 推移が見える
- [ ] detail_tab に投稿後の伸びを示す line chart と cost_per_view が出る
- [ ] `v_performance` の `LEFT JOIN` が `v_active_posts` 経由に変わり、rollback 済 post が概要タブの集計から消える
- [ ] dashboard を起動して既存データ (= 既に DB に保存されている post_metrics / experiment_assignments) で全タブが正常表示される

### Phase B 完了条件

- [ ] `analytics/schema.sql` schema_version = 10
- [ ] `post_metrics` に 6 列 (`impressions, subscribers_gained, traffic_*_pct × 4`) が追加されている
- [ ] `post_retention_curves` テーブルが作成され、`fetch_metrics --platform youtube` 実行で行が積まれる
- [ ] `youtube.fetch_analytics` の return に `impressions, ctr, subscribers_gained` が含まれる
- [ ] `youtube.fetch_traffic_sources` / `youtube.fetch_retention_curve` が実装されている
- [ ] dashboard detail_tab に CTR / impressions / 30 秒地点 retention / traffic source pie chart が出る
- [ ] 既存テスト + 新規 unit test が pass

### Phase C 完了条件

- [ ] `analytics/schema.sql` schema_version = 11
- [ ] `screenplays` に `transformation, tree_main_branch, pov_id` 3 列が追加されている
- [ ] `scripts/ingest_screenplay.py` の auto_tag が 3 列を埋める
- [ ] `config/transformation_taxonomy.yaml` が運用者管理ファイルとして存在する
- [ ] `v_transformation_performance` / `v_halo_effect` view が作成されている
- [ ] dashboard 最上位に「Transformation」タブがあり、Branch 別の集計が出る
- [ ] outlier 動画 1 本以上ある状態で Halo effect view に行が返る

---

## 5. 実装ロードマップ + 依存関係

```
Phase A (1〜2 日)
├─ A-1: 戦略軸タブ          ─┐
├─ A-2: 実験タブ              │ (= 並列可)
├─ A-3: 品質タブ              │
├─ A-4: detail 時系列+ROI    ─┘
└─ A-5: v_performance 修正  (= A-4 の前にやる)

         ↓ (Phase A の効用が確認できたら)

Phase B (3〜5 日)
├─ B-1: schema migration v10            (= 最初)
├─ B-2: fetch_analytics 拡張            ─┐
├─ B-3: fetch_traffic_sources            │ (= 並列可、B-1 後)
├─ B-4: fetch_retention_curve           ─┘
├─ B-5: fetch_metrics.py 配線            (= B-2/3/4 後)
└─ B-6: dashboard で 30秒 retention 表示 (= B-5 後)

         ↓ (Phase B の数値が出始めたら)

Phase C (1〜2 週)
├─ C-1: schema migration v11        (= 最初)
├─ C-2: auto_tag pass 拡張           (= C-1 後)
├─ C-3: Halo effect view             (= C-1 後)
└─ C-4: dashboard 最上位タブ再編     (= C-2/C-3 後)
```

---

## 6. 影響範囲一覧 (= ファイル別)

| ファイル                                     | Phase A               | Phase B                 | Phase C                |
| -------------------------------------------- | --------------------- | ----------------------- | ---------------------- |
| `scripts/dashboard.py`                       | ✏️ タブ 3 つ追加      | ✏️ retention chart 追加 | ✏️ 最上位タブ再編      |
| `analytics/db.py`                            | ✏️ 時系列 query 関数  | ✏️ migration v10        | ✏️ migration v11       |
| `analytics/schema.sql`                       | ✏️ v_performance 修正 | ✏️ v10 columns + table  | ✏️ v11 columns + views |
| `platform_clients/youtube.py`                | -                     | ✏️ 3 関数追加           | -                      |
| `scripts/fetch_metrics.py`                   | -                     | ✏️ retention insert     | -                      |
| `scripts/ingest_screenplay.py`               | -                     | -                       | ✏️ auto_tag 拡張       |
| `config/transformation_taxonomy.yaml` (新設) | -                     | -                       | ✨ 新設                |
| `tests/analytics/*.py`                       | ✏️ dashboard test     | ✏️ schema/fetcher test  | ✏️ auto_tag test       |

---

## 7. リスクと緩和策

### R-1: YouTube Analytics API quota 超過

`fetch_retention_curve` は post 1 件あたり追加 1 API call。日次で全 post を fetch すると quota が現実的に逼迫する。

**緩和策**: `fetch_metrics.py` の retention curve fetch は (a) 投稿後 7 日以内の post のみ、(b) かつ前回 fetch から 24h 以上空いた post のみ、を対象にする。古い post は curve を再取得しない。

### R-2: `audienceWatchRatio` は視聴 view 数が少ない動画では返ってこない

YouTube Analytics は **規定数以上の視聴がない動画には retention curve を返さない** (= プライバシー / ノイズ排除)。

**緩和策**: `fetch_retention_curve` は空配列を return しても fail せず、dashboard 側で「retention curve は視聴数が一定以上で取得可能」というメッセージを出す。

### R-3: schema migration のロールバック

ALTER TABLE ADD COLUMN は SQLite では rollback できない (= 列削除には rebuild が必要)。

**緩和策**: 各 Phase 着手前に `data/analytics.db` のバックアップを `data/analytics.db.pre-v10.bak` 等に取る運用を docs に明記。本番投入前に自動 backup を `init_db()` に追加することも検討。

### R-4: Halo effect view のパフォーマンス

`v_halo_effect` は self-join + window-like 集計で post 数が増えると遅くなる。

**緩和策**: post 数 < 1000 なら問題なし。1000 を超える時点で **materialized table** (= `halo_effect_snapshot` テーブルを cron で再構築) に置き換える設計余地を残す。

### R-5: Transformation auto_tag の精度

Claude Haiku が 1 台本から正しい transformation を抽出できない場合がある (= 抽象的すぎる / 短い台本)。

**緩和策**: (a) `transformation` カラムは nullable、(b) dashboard 側で `transformation IS NULL` の台本を「未分類」として可視化、(c) 後から手動編集 UI (= preview UI に追加) を Phase D の検討項目として残す。

---

## 8. 範囲外 (= 本 doc が扱わないこと)

以下は**意図的に本 doc のスコープから外す**:

- **Instagram / TikTok の retention 取得** — API 仕様により原理的に取れない (= TikTok Studio CSV 経由は既存)
- **Preview UI (= React frontend) への metrics 表示** — 別 doc で検討。本 doc は Streamlit dashboard の準拠化に閉じる
- **bandit 実装の改修** — `experiment_assignments` への書き込み側は別 plannings (= Phase 3 closed-loop) で議論済
- **コスト警告 / 予算アラート** — `cost_tracking` 系は `architecture-decisions.md §5` で定義済の経路に従う

---

## 9. 参照

- `docs/content-strategy.md` — 動画戦略の根本 (= 本 doc の "正" の半分)
- `docs/architecture-decisions.md §5` — コスト構造、cost_tracking 設計
- `analytics/schema.sql` — DB スキーマ (= 本 doc の "正" の残り半分)
- `scripts/dashboard.py` — 修正対象の Streamlit dashboard
- `platform_clients/youtube.py` — fetch 拡張対象
- `docs/plannings/2026-05-07_full-automation-implementation-plan.md` — Phase 0/3 closed-loop の元設計
- `docs/plannings/2026-05-10_architecture-mismatch-audit.md` — 別領域の同種 audit (= 構成参考)
