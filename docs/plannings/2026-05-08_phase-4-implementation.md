# Phase 4 実装記録 (= 本番展開準備)

**date**: 2026-05-08 / **PR**: #72 / **branch**: `feat/phase-4-production`

`docs/plannings/2026-05-07_full-automation-implementation-plan.md` §6 (Phase 4) に対応。

実装計画原文:

> - 本番公開フローに **人間 gate を残す or 完全自動** を選択 (= ここはビジネス判断)
> - 監査ログ: 全公開動画の `generation_records` を凍結保存
> - rollback 手順: YouTube からの取り下げ + IG/TikTok の削除 を 1 コマンド化

## 設計判断 (= 計画書原案からの逸脱)

| 計画書原案                                                                   | 実装                                                             | 理由                                                                                                                                                                                                                     |
| ---------------------------------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `PRODUCTION_HUMAN_GATE_ENABLED` を auto_loop に組み込み、 publish 直前で停止 | **env だけ用意し auto_loop からは参照しない**                    | 「ビジネス判断」と計画書にも明記されているとおり、本番アカウント切替時に運用者が flag をどう扱うか決める。env が立っているだけでも `AUTO_LOOP_ALLOW_PUBLIC=0` (Phase 1) と二重防衛になり、暴発はそもそも起こらない設計。 |
| rollback で YouTube 動画を削除                                               | **`privacyStatus=private` に降格**                               | 削除は復元不能。`private` なら誤 rollback でも復旧できる + 統計は維持。完全削除が必要ならユーザが YouTube Studio で行う運用。                                                                                            |
| rollback で IG / TikTok の API 削除を実装                                    | **`manual_required` を返して Slack 通知のみ**                    | 両 platform の削除 API は OAuth scope の追加申請が必要。Phase 4 のスコープを「クリティカル経路の自動化」に絞るため、半自動 (= 手動削除を促す通知) に留める。Phase 4.5 / 5 で API 完全自動化。                            |
| audit_freeze で全テーブルを毎回 dump                                         | **`since YYYY-MM-DD` で範囲絞り**                                | 累計データが大きくなると毎日凍結はディスクを圧迫する。月次で `--since` を指定し increment dump する運用を想定。                                                                                                          |
| `experiment_assignments.video_id` の backfill を auto_loop に組み込み        | **手動関数 `backfill_experiment_assignments_video_id` のみ提供** | ingest_video 完了タイミング (= Stage 7 final_import 後) で呼ぶべきだが、その経路は preview_server / final_import 側の改修が必要。Phase 4 では関数だけ用意し、ingest_video.py 拡張は Phase 4.5 で。                       |

## 二重防衛の構造

本番アカウント公開を抑止する gate は 2 段:

```
auto_loop が privacy="public" で publish 要求
    │
    ▼
config.AUTO_LOOP_ALLOW_PUBLIC=0 (= 既定)?
    │
    ├─ Yes (= 既定) → privacy=unlisted に降格 (Phase 1: youtube._resolve_privacy)
    │                  ※ ここで止まるので Phase 4 の human gate は発火しない
    │
    └─ No  (= AUTO_LOOP_ALLOW_PUBLIC=1) → privacy=public のまま
                                            │
                                            ▼
                            config.PRODUCTION_HUMAN_GATE_ENABLED=1?
                                            │
                                            ├─ Yes → 運用者が手動で承認
                                            │       (= 現状実装は無、ビジネス判断後に
                                            │          auto_loop に組み込み)
                                            │
                                            └─ No  → 完全自動公開
```

`PRODUCTION_HUMAN_GATE_ENABLED` は **env を用意しただけ**。auto_loop の `_publish_youtube` から参照していない。本番アカウント切替時に「どう gate するか」をビジネス判断した上で auto_loop に組み込む想定 (= Slack approval / Studio 手動 unlisted→public / 別 cron で承認待ちキューを処理する等)。

## audit_freeze のフォーマット

```
data/audit_freezes/<YYYY-MM-DD_HHMMSS>/
├── _metadata.json
├── generation_records.jsonl
├── experiment_assignments.jsonl
├── qa_failures.jsonl
├── videos.jsonl
├── posts.jsonl
├── post_metrics.jsonl
└── screenplays.jsonl
```

`_metadata.json`:

```json
{
  "frozen_at": "2026-05-08T12:00:00+00:00",
  "since": "2026-05-01",
  "schema_version": 6,
  "row_counts": {
    "generation_records": 142,
    "experiment_assignments": 286,
    ...
  }
}
```

`schema_version` を保存することで、将来 schema が v7 / v8 に進んだ後でも凍結ファイルの layout が辿れる。

## rollback の運用

```bash
# 1 video の全 platform を取り下げ
python3 scripts/rollback.py <video_id>

# YouTube だけ取り下げ
python3 scripts/rollback.py <video_id> --platform youtube
```

| platform  | 動作                              | 副作用                                              |
| --------- | --------------------------------- | --------------------------------------------------- |
| YouTube   | Data API で privacyStatus=private | 統計は維持、URL は alive (= private で見えないだけ) |
| Instagram | Slack 通知のみ                    | 運用者が Studio から手動削除                        |
| TikTok    | 同上                              | 同上                                                |

**posts テーブルには rollback 履歴を書かない**。理由は schema を変えると Phase 0/1/2/3 の migration 経路がややこしくなるため。代わりに `audit_freeze` 後の差分で「rollback された post」を後追いできる (= Slack 通知 + audit_freeze 履歴で十分)。

## 出口 KPI チェック

> Phase 4 出口 KPI: 本番アカウントで 1 ヶ月、品質クレームゼロ、人間レビュー率 < 10%

| 項目                                | 状態                                                                                         |
| ----------------------------------- | -------------------------------------------------------------------------------------------- |
| 監査ログ凍結                        | ✅ `scripts/audit_freeze.py`                                                                 |
| rollback 1 コマンド                 | ✅ `scripts/rollback.py` (= YouTube は完全自動、IG/TikTok は半自動)                          |
| improvement validate                | ✅ config 起動時に warn + fallback                                                           |
| `PRODUCTION_HUMAN_GATE_ENABLED` env | ✅ 用意 (= auto_loop 反映はビジネス判断時)                                                   |
| backfill 関数                       | ✅ `analytics.db.backfill_experiment_assignments_video_id` (= ingest_video 拡張は Phase 4.5) |
| 本番アカウントで 1 ヶ月             | ⏳ **実運用検証**。AUTO_LOOP_ALLOW_PUBLIC=1 切替後にカウント開始                             |
| 品質クレームゼロ                    | ⏳ **実運用検証**                                                                            |
| 人間レビュー率 < 10%                | ⏳ **実運用検証**                                                                            |

つまり**コードのインフラは揃った** が、実運用で 1 ヶ月走らせて KPI を測るのはユーザ側で行う。

## Phase 4.5 / 5 で踏むべき残課題

- `auto_loop` に `PRODUCTION_HUMAN_GATE_ENABLED=1` の挙動を組み込み (= Slack approval / 承認キュー)
- `scripts/ingest_video.py` 拡張で `backfill_experiment_assignments_video_id` を自動呼出
- IG / TikTok の API 削除実装 (= scope 申請後)
- `posts` テーブルに `rollback_at` / `rollback_reason` カラムを追加 (= schema v7)
- `audit_freeze` の自動 rotate (= 30 日経過した freeze を S3 等に退避してローカル削除)
- `v_strategy_performance` view 追加 (Phase 3 の残課題)。`active_explore` / `active_exploit` 別の reward 集計
- `posts.rollback_at` を join する `v_active_posts` view (= rollback 後の post を集計から除外)

## 全 Phase 完成

Phase 0 → 1 → 2 → 3 → 4 が揃ったことで、フルオート量産経路の **コード基盤** は完成。実運用での KPI 達成は順次:

| Phase | 出口 KPI                                  | 達成方法                                               |
| ----- | ----------------------------------------- | ------------------------------------------------------ |
| 0     | qa_failures ≥ 30, generation_records 完備 | 手動運用継続でデータ蓄積                               |
| 1     | 7 日 21/21 cron 成功                      | `auto_loop.py` を cron で 1 日 3 回                    |
| 2     | 30 本連続 reject < 5%, recall ≥ 80%       | `eval_validators.py` 週次回し、しきい値調整            |
| 3     | A/B p<0.05 で改善群が有意                 | `IMPROVEMENT_STRATEGY=shadow` 2 週間 → `active` で A/B |
| 4     | 本番 1 ヶ月、人間レビュー率 < 10%         | `AUTO_LOOP_ALLOW_PUBLIC=1` 切替 + 監査ログ運用         |

各 Phase 出口 KPI をユーザ側で達成するたびに、次 Phase の本格運用に進める構造です。
