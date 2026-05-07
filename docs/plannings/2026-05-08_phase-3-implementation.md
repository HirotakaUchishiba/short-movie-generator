# Phase 3 実装記録 (= Closed-loop 改善)

**date**: 2026-05-08 / **PR**: #71 / **branch**: `feat/phase-3-closedloop`

`docs/plannings/2026-05-07_full-automation-implementation-plan.md` §5 (Phase 3) の B-3.1 / D-3.2 / D-3.3 / B-3.4 / D-3.5 を一括実装。

## 設計判断 (= 計画書原案からの逸脱)

| 計画書原案                                                      | 実装                                               | 理由                                                                                                                                                                                                                                           |
| --------------------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `experiment_assignments.video_id` は `videos(id)` を REFERENCES | **TEXT NOT NULL (FK 無し) で ts ベースで運用**     | `videos.id` は ingest_video 後に決まる (= sha256[:12])。Phase 3 で書き込む段階では `ts` (= temp/<TS>) しか知らない。後で `update_experiment_assignments(ts, video_id=...)` で backfill する経路を Phase 4 / fetch_metrics 拡張で追加する想定。 |
| 軸ごとに独立 bandit instance                                    | **毎回 `select_assignments_for_video()` で再構築** | 1 invocation = 1 動画。bandit 状態を永続化する代わりに、history (= v_axis_performance) を毎回読み直して reconstruct。これで「どの bandit を使ったか」のバージョン管理が要らない。                                                              |
| Thompson sampling への切替                                      | **ε-greedy のみ実装、Thompson は Phase 3.5+ 候補** | サンプル ≥ 200 で意味のある posterior が出るが、Phase 3 序盤では履歴薄。ε-greedy で十分。                                                                                                                                                      |
| Anthropic system prompt を直接書き換え                          | **`analyze.run` の `options.instructions` 経由**   | 既存 instructions オプションに乗せれば analyze 側に変更不要。auto_loop だけで完結する。                                                                                                                                                        |

## モジュール責務

| module                         | 役割                                    | 依存                                              |
| ------------------------------ | --------------------------------------- | ------------------------------------------------- |
| `improvement.bandit`           | ε-greedy の純粋アルゴリズム             | なし (= 標準ライブラリのみ)                       |
| `improvement.axis_performance` | `v_axis_performance` を読む reader      | analytics.db                                      |
| `improvement.prompt_injector`  | Claude system prompt 用文字列の組み立て | config + axis_performance                         |
| `improvement.strategy`         | `IMPROVEMENT_STRATEGY` の dispatch      | config + analytics.db + bandit + axis_performance |

`auto_loop` は `strategy.select_assignments_for_video()` + `strategy.record_assignments(ts, assignments)` だけ呼べば全経路が動く。

## 経路 (active strategy)

```
fetch_reference
   │
   ▼
strategy.select_assignments_for_video()
   │  → 各軸で v_axis_performance から history 読み込み
   │  → ε-greedy で (value, "explore"|"exploit") を選択
   ▼
prompt_injector.compose_instructions(assignments)
   │  → "## 過去 30 日の高パフォーマンス傾向" + "## 今回意図的に試す軸"
   ▼
analyze.run(video_path=..., options=AnalyzeOptions(instructions=...))
   │  → Claude に上記 instructions を system prompt で渡す
   │  → screenplays/auto_<sha>.json
   ▼
create_project (= ts 発行)
   │
   ▼
strategy.record_assignments(ts, assignments)
   │  → experiment_assignments に <axis, value, "active_<sub>"> を 1 行ずつ
   ▼
... 各 stage ... → publish
```

## strategy / sub_strategy のフォーマット

`experiment_assignments.strategy` は `<overall>_<sub>` 形式:

| overall    | sub                   | 意味                                        |
| ---------- | --------------------- | ------------------------------------------- |
| `baseline` | (記録されない)        | bandit 完全無効                             |
| `shadow`   | `explore` / `exploit` | bandit 選択は記録するが prompt には載せない |
| `active`   | `explore` / `exploit` | 記録 + prompt 注入                          |

A/B 検定では `strategy LIKE 'baseline%'` vs `strategy LIKE 'active%'` で対照群を比較。`shadow` は本番投入前のシャドウ稼働 (= 影響評価) のための中間フェーズ。

## 出口 KPI チェック

> Phase 3 出口 KPI: A/B 検定でベースライン群 vs 改善群 (= バンディット選択) に有意差 (例: 完視聴率 +10%, p<0.05)

| 項目                              | 状態                                                                                                         |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `experiment_assignments` テーブル | ✅ schema v6 で追加                                                                                          |
| `v_axis_performance` view         | ✅ 投稿後 24h 経過 filter 込みで追加                                                                         |
| ε-greedy bandit 実装              | ✅ `improvement.bandit.EpsilonGreedyBandit`                                                                  |
| prompt 注入経路                   | ✅ `compose_instructions` → `analyze.run(... options=AnalyzeOptions(instructions=...))`                      |
| 3 段階切替                        | ✅ `IMPROVEMENT_STRATEGY` (baseline / shadow / active)                                                       |
| reward update 経路                | ⏳ Phase 3.5 で `scripts/fetch_metrics.py` 拡張 (= post_metrics 取得時に bandit reward に反映)               |
| A/B 有意差                        | ⏳ **実運用検証**。`shadow` で 2 週間データ蓄積 → `active` で A/B 検定 (= 統計検定スクリプトは Phase 3.5 で) |

つまり**バンディット選択 + prompt 注入の経路は揃った** が、reward 反映の自動化と統計検定は Phase 3.5 / 4 で実装する。

## reward 反映の TODO (Phase 3.5)

現状の `v_axis_performance` は `screenplays.hook_type / tone / dominant_emotion / theme` を group key とした集計。これは「screenplay の自動タグ」が reward の単位。`experiment_assignments` の値 (= 今回試した値) と一致しているのでそのまま reward source として使える。

ただし、**`active_explore` / `active_exploit` で生成された動画の reward を、その strategy 単位で別々に集計する**方が A/B 検定として正確 (= 同じ hook_type でも shadow と active で生成方法が違う = 別母集団)。

```sql
-- Phase 3.5 で追加する想定の view
CREATE VIEW v_strategy_performance AS
SELECT
    e.strategy, e.axis, e.selected_value,
    AVG(m.completion_rate) AS avg_completion,
    AVG(m.saves) AS avg_save,
    COUNT(*) AS n
FROM experiment_assignments e
JOIN videos v ON v.id = e.video_id  -- 要 video_id backfill
JOIN posts p ON p.video_id = v.id
LEFT JOIN v_latest_metrics m ON m.post_id = p.id
WHERE p.posted_at IS NOT NULL
  AND julianday(m.fetched_at) - julianday(p.posted_at) >= 1.0
GROUP BY e.strategy, e.axis, e.selected_value;
```

これがあれば bandit reward を `strategy=active_*` に絞って取れるので、shadow 期間のノイズが入らない。

## 残課題

- `experiment_assignments.video_id` の backfill (= ts → videos.id への置換) が未実装。当面は ts でも分析できるが、CASCADE delete の整合のため Phase 4 で `update_experiment_assignments_video_id(ts, video_id)` を追加
- `IMPROVEMENT_STRATEGY` の値が typo すると baseline 扱いではなく shadow / active 扱いされない (= compose_instructions が None を返すだけ)。Phase 4 で起動時 validate を追加
- bandit 状態を永続化していない (= 毎回 reconstruct)。サンプル ≥ 200 になり Thompson sampling に移行する場合は posterior が必要 → 永続化が必要
- prompt_injector の test が `monkeypatch.setattr("improvement.prompt_injector.axis_performance", type("M", ...))` で module を入れ替えているが、Pythonic でない。`unittest.mock.patch.object` で関数を patch する方が綺麗
- `select_assignments_for_video` 内の bandit instance を毎回構築するコストは現状 ms オーダーだが、history が爆発した場合 (= 軸 × 1000 件) は per-call 構築を諦めて在庫管理する想定
