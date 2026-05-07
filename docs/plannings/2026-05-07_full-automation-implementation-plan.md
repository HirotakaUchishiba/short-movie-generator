# 高品質フルオート完成までの実装計画

本ドキュメントは「cron で参考動画を取得 → 抽象台本生成 → 本パイプラインを完全自動実行 → SNS 公開 → メトリクス取得 → 次回生成へフィードバック」という閉ループを **品質を毀損せずに** 完成させるための綿密な実装計画を残す。判定根拠と全体俯瞰は `docs/full-automation-feasibility.md` を参照。

各 Phase は **入口条件 / 出口 KPI / タスク / ロールバック** を厳密に持ち、KPI を満たさない限り次に進まない。「進んだ気になる」を構造的に防ぐのが眼目。

---

## 0. 設計原則 (= 全 Phase 共通の制約)

| 原則                 | 具体的な意味                                                                             |
| -------------------- | ---------------------------------------------------------------------------------------- |
| 計測ファースト       | 自動化の前に DB スキーマと dump 機構を確定する。後付けは過去データを失う                 |
| 段階的閉ループ       | open-loop → QA → closed-loop の順で薄く重ねる。同時投入はシグナル汚染で詰む              |
| 信用毀損ゼロ         | Phase 4 まで公開先は **実験用アカウントまたは unlisted** に強制。本番への移行は人間 gate |
| データ駆動の閾値決定 | validator のしきい値は QA failures の実例を見て決める。先に決めない                      |
| 退路を必ず残す       | 各層に kill-switch / 人手介入点を持つ。どの Phase でも 1 コマンドで全自動を止められる    |
| idempotent と可観測  | cron で同じ stage を 2 回叩いても壊れない。何が起きたかは全部 generation_records に残る  |

---

## 1. ロードマップ全体

5 つの **並行トラック** を時系列の **Phase** で組み合わせる。トラックを縦・Phase を横に置いた行列:

| Track \ Phase                | **0. 計測基盤** (1〜2 週)                                        | **1. Open-loop 量産** (1〜2 週) | **2. 自動 QA** (~1 ヶ月)       | **3. Closed-loop 改善** (1〜2 ヶ月)           | **4. 本番展開** (任意) |
| ---------------------------- | ---------------------------------------------------------------- | ------------------------------- | ------------------------------ | --------------------------------------------- | ---------------------- |
| **A. 量産経路** (Stage 1〜9) | 現状維持                                                         | **新設**: cron + auto-approve   | retry 強化                     | 改善 logic 接続                               | 本番アカウント切替     |
| **B. 計測・データ基盤**      | **新設**: generation_records, qa_failures, reference_videos 拡張 | 拡張: cron run logs             | 拡張: validator scores         | 拡張: experiment_assignments                  | 監査ログ               |
| **C. 品質保証 (QA)**         | 暫定ヒューリスティック (silence のみ)                            | 暫定継続                        | **本実装**: validator スイート | 改善 (= 失敗例で再訓練)                       | exploration 制御       |
| **D. 改善ロジック**          | —                                                                | —                               | —                              | **新設**: 多腕バンディット + prompt injection | A/B 監視               |
| **E. 運用**                  | kill-switch                                                      | cron + Slack alert + cost guard | failure budget                 | A/B 切替                                      | rollback 手順          |

各 Phase の出口 KPI は数値で固定する:

| Phase | 出口 KPI                                                                                                           |
| ----- | ------------------------------------------------------------------------------------------------------------------ |
| 0     | 不良サンプル ≥ 10 / 正常サンプル ≥ 10 / generation_records スキーマ確定 / 全 stage で seed / prompt / retry が残る |
| 1     | 7 日連続で **1 日 3 本** のフルパイプ成功 (= 21/21 が cron 経由で publish まで到達)。公開先 unlisted               |
| 2     | 直近 30 本連続で **人間レビュー reject 率 < 5%**                                                                   |
| 3     | A/B 検定で改善群がベースライン群を有意に上回る (例: 完視聴率 +10%, p<0.05)                                         |
| 4     | 本番アカウントで 1 ヶ月、品質クレームゼロ、人間レビュー率 < 10%                                                    |

---

## 2. Phase 0: 計測基盤と暗黙知の言語化 (1〜2 週)

### 目的

「何が不良か」「何が正常か」を物理的に手元に揃える。Phase 2 の validator はこのデータが無ければ書けない。

### 入口条件

現状 (= 手動運用)。何も前提条件無し。

### 出口 KPI

- `data/qa_failures/` に **不良サンプル ≥ 10 件**、各々にカテゴリタグと screenplay snapshot
- **正常サンプル ≥ 10 件** (= 公開承認した動画) の generation_records が完全に残っている
- `generation_records` / `qa_failures` テーブルがマイグレーション済みで、本番運用に耐える
- 全 stage の seed / prompt / API レスポンスメタが残っている

### タスク

#### B-0.1 DB マイグレーション

`analytics/schema.sql` に追加:

```sql
CREATE TABLE generation_records (
  video_id      INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,                 -- temp/<TS>
  reference_video_id INTEGER,                  -- analyze 経由なら参考動画
  screenplay_sha TEXT,
  stage_runs    JSON,                          -- [{stage, started_at, ended_at, retry_count, status, cost_usd}]
  prompts       JSON,                          -- {bg: [{scene_idx, prompt}], anim: [...], tts: {...}}
  seeds         JSON,                          -- imagen / kling の seed
  api_meta      JSON,                          -- レスポンスID等の追跡情報
  total_cost_usd REAL,
  validator_scores JSON,                       -- Phase 2 で埋める
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE qa_failures (
  id            INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,
  stage         TEXT NOT NULL,                 -- script/tts/bg/kling/scene/overlay/final/publish
  scene_idx     INTEGER,
  line_idx      INTEGER,
  tags          JSON NOT NULL,                 -- ["character_drift", "subtitle_zone_blocked"]
  note          TEXT,
  source        TEXT NOT NULL,                 -- "human_reject" / "auto_flagged" / "post_publish_lowperf"
  artifact_path TEXT,                          -- data/qa_failures/<TS>_<stage>_<n>/artifact.*
  screenplay_snapshot_path TEXT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE reference_videos ADD COLUMN source_url TEXT;
ALTER TABLE reference_videos ADD COLUMN fetched_at DATETIME;
ALTER TABLE reference_videos ADD COLUMN license_status TEXT;     -- "user_owned" / "fair_use_review" / "public_domain"
```

#### A-0.2 reject API + UI

`preview_server.py` に `POST /api/projects/<TS>/reject` を新設。受け取った body で `data/qa_failures/<TS>_<stage>_<n>/` を作り、`artifact` `screenplay_snapshot.json` `meta.json` をコピー、SQLite の `qa_failures` テーブルにも 1 行追加。承認 UI に NG ボタン + カテゴリ enum チェックボックス + 一行 note 欄を追加。

カテゴリ enum (= visual / audio / lipsync / subtitle / story の 5 軸):

```python
QA_FAILURE_TAGS = [
    "character_drift", "storyboard_layout", "composition_off", "subtitle_zone_blocked",
    "audio_silence", "audio_clipping", "audio_mispronounce", "audio_wrong_emotion",
    "lipsync_mouth_off", "lipsync_no_movement", "lipsync_timing_off",
    "subtitle_overlap_subject", "subtitle_off_screen", "subtitle_too_long",
    "story_pacing_off", "story_hook_weak",
]
```

#### B-0.3 既存 cost_records.jsonl の拡張

各 stage 完了時に `generation_records.stage_runs` に append。現状の `data/cost_records.jsonl` は **analyze pipeline のみ** なので、Stage 2-9 でも記録するようにフックを足す。

#### A-0.4 regenerate 時の自動アーカイブ

UI の「再生成」ボタンの裏で、**前世代を無条件で `data/qa_failures/<TS>_<stage>_<n>/?source=regenerate_implicit/` にコピー**。意識的な reject じゃなくても、暗黙の不良が拾える経路を確保する。

#### E-0.5 kill-switch

`config.DISABLE_AUTO_LOOP=True` の env var を確認するゲートを `main.py` 冒頭に置く。Phase 0 では未使用だが、後続 Phase の前提として先に入れておく。

#### 0.6 手動運用で 10-20 本作る

ここは「Phase 0 で初めてやる作業」ではなく、**既存運用を続けながら勝手にデータが溜まる** 状態にしておくのが理想。だから 0.1-0.5 を **データ収集を始める前** に終わらせる。

### ロールバック

Phase 0 のマイグレーションは追加のみで既存に破壊的でない。reject API は新エンドポイントなので既存承認フローに影響なし。問題があれば該当 endpoint だけ無効化。

---

## 3. Phase 1: Open-loop 量産 (1〜2 週)

### 目的

人手介入なしで「参考動画 URL → YouTube 公開」が 1 コマンドで通る経路を作る。**改善ロジックは入れない**。

### 入口条件

Phase 0 の出口 KPI が満たされていること。特に generation_records が全 stage で書かれることが必須 (= 後で量産の挙動を分析する材料)。

### 出口 KPI

- **7 日連続で 1 日 3 本** の cron が成功 (= 21/21 が publish まで到達)
- **公開先は unlisted または実験用アカウント** に固定
- 失敗時 Slack 通知が届く
- 人間レビュー reject 率は問わない (= まだ高くて良い)

### タスク

#### A-1.1 yt-dlp wrapper

`scripts/fetch_reference.py` 新設:

```bash
python3 scripts/fetch_reference.py <URL> \
  --license user_owned \
  --max-duration 90
# → reference_videos/<sha>.mp4 + DB 登録 (source_url, fetched_at, license_status)
```

ライセンス確認をスキーマ上強制 (= `license_status` が `"unconfirmed"` だと analyze に進めない)。著作権配慮を運用に組み込む。

#### A-1.2 orchestrator

`scripts/auto_loop.py` 新設。1 動画分のチェイン:

```python
def run_one_video(reference_url: str, dry_run: bool = False) -> str:
    if os.environ.get("DISABLE_AUTO_LOOP") == "1":
        raise SystemExit("auto loop disabled by env")

    check_daily_cap()
    check_monthly_budget()

    ref_path = fetch_reference(reference_url)         # yt-dlp + DB
    sp_name = run_analyze(ref_path)                    # → screenplays/auto_<sha>.json
    ts = create_project(sp_name)                       # → temp/<TS>/

    for stage in ["script", "tts", "bg", "kling", "scene", "overlay"]:
        run_stage(sp_name, ts)                         # python3 main.py ... --resume <TS>
        run_validator_provisional(ts, stage)            # Phase 1 では silence/clip のみ
        approve(ts, stage)                              # POST /api/projects/<TS>/approve

    import_final_as_canonical(ts)                       # raw を canonical 化 (CapCut スキップ)
    publish(ts, platform="youtube", privacy="unlisted")  # ← unlisted 強制
    return ts
```

cron は `scripts/auto_loop.py` を 1 日数回呼び出すだけ。

#### A-1.3 approve REST chain

既存の `POST /api/projects/<TS>/approve` を `auto_loop.py` から `requests` で叩く。エラーは raise してそこで止める。

#### C-1.4 暫定 validator (= silence/clip のみ)

`qa/validators_provisional.py`:

- 各 `tts_<S>_<L>.mp3` を `ffmpeg volumedetect` で平均 dB と silence ratio を測る
- mean_dB < -45 または silence_ratio > 50% で **fail**
- 各 `kling_<S>.mp4` の音声トラック / 全黒フレームをチェック
- fail なら `qa_failures` に `source="auto_flagged"` で書きつつ stage 再実行 (= retry 1 回まで)

#### E-1.5 通知

`scripts/auto_loop.py` の各失敗箇所で `notify_slack(level, message)`。最小限の webhook 1 本。env: `SLACK_WEBHOOK_URL`。

#### E-1.6 cost guard

`generation_records.total_cost_usd` を見て、**当日の cost 合計** と **当月の cost 合計** をチェック。env: `DAILY_COST_CAP_USD=20` `MONTHLY_COST_CAP_USD=300`。超えたら fail-fast + Slack 通知。

#### E-1.7 公開先強制

`platform_clients/youtube.py` の `upload()` で `privacy="unlisted"` を強制。env: `AUTO_LOOP_ALLOW_PUBLIC=0` でない限り `private/public` を許可しない。

### ロールバック

`DISABLE_AUTO_LOOP=1` の env で cron 即停止。生成済み動画は手動で取り下げ可能。unlisted なので拡散リスクは低い。

---

## 4. Phase 2: 自動 QA Validator の本実装 (~1 ヶ月)

### 目的

Phase 1 の暫定 validator (silence のみ) を **多軸の本実装** に置き換え、不良率を 5% 未満に下げる。

### 入口条件

- Phase 1 の出口 KPI が満たされている
- `qa_failures` テーブルに **不良 ≥ 30 件** (= Phase 0 + Phase 1 の自動 reject 含む)
- カテゴリタグごとの分布が見える (= どの不良が頻発しているかが判明している)

### 出口 KPI

- 直近 30 本の自動量産で **人間レビュー reject 率 < 5%**
- validator のリコール (= 人間が見つけた不良のうち validator がキャッチしたもの) **≥ 80%**
- validator の適合率 (= validator が NG にしたもののうち本当に不良) **≥ 70%**

### タスク

#### C-2.1 validator スイート

`qa/validators/` 配下に軸ごとに 1 ファイル:

| Validator                 | 入力                                             | 手法                                                              | 失敗条件 (初期しきい値は Phase 0 データから決める) |
| ------------------------- | ------------------------------------------------ | ----------------------------------------------------------------- | -------------------------------------------------- |
| `audio_silence.py`        | `tts_*.mp3`                                      | ffmpeg volumedetect + silencedetect                               | silence_ratio > 30% or mean_dB < -45               |
| `audio_clipping.py`       | `tts_*.mp3`                                      | librosa peak / true_peak                                          | true_peak > -0.1 dBFS                              |
| `subtitle_overlap.py`     | `bg_<S>.png` + 字幕 bbox                         | scene segmentation (= U^2-Net 等) で被写体 mask、字幕領域との IoU | IoU > 0.4                                          |
| `character_drift.py`      | `kling_<S>.mp4` の代表フレーム + reference image | CLIP image embedding cosine 距離                                  | distance > 閾値 (Phase 0 正常データから baseline)  |
| `lipsync_quality.py`      | `scene_<S>.mp4`                                  | mouth-region 動き量 (optical flow) と音声 RMS の相関              | corr < 0.3                                         |
| `subtitle_readability.py` | overlay の ASS スタイル + 動画フレーム           | フォントサイズ / コントラスト比                                   | contrast < 4.5:1                                   |
| `story_pacing.py`         | screenplay                                       | line 文字数 / scene 秒数比                                        | line WPM 換算 > 600 文字/分                        |

各 validator は単純な `def validate(artifact_path, context) -> ValidationResult` シグネチャ。`ValidationResult` は `{passed: bool, score: float, reason: str}`。

#### C-2.2 retry hook の整備

各 stage で validator が NG を出したら、その stage の retry を最大 N 回 (= TTS は 2 回 / Kling は 3 回 / lipsync は 2 回)。retry も全部 NG なら `qa_failures` に `source="auto_flagged"` で記録、その動画は `generation_records.status="auto_rejected"` で **publish しない**。

#### C-2.3 validator の評価ループ

週次で `qa/eval_validators.py` を回す:

- 直近 30 本の `qa_failures` を見て、各 validator のリコール / 適合率を出す
- 閾値が緩すぎる / 厳しすぎる validator は警告
- 結果を `data/validator_eval/<week>.json` に蓄積

人間が validator のしきい値を調整する判断材料にする。**この時点では自動チューニングはしない**。

#### B-2.4 generation_records.validator_scores の拡張

各 validator のスコアを動画ごとに残す (= Phase 3 で「validator score と metrics の相関」を見るため)。

### ロールバック

`config.QA_VALIDATORS_ENABLED=False` で全 validator を skip して Phase 1 状態に戻る。validator 単位でも `config.QA_VALIDATOR_BLACKLIST=["lipsync_quality"]` で個別無効化可能。

---

## 5. Phase 3: Closed-loop 改善ロジック (1〜2 ヶ月)

### 目的

メトリクス (= views / completion_rate / save_rate) を hook_type / tone / emotion / theme / location_ref などの軸で集計し、**次回生成のバイアス** にする。

### 入口条件

- Phase 2 の出口 KPI が満たされている (= 不良率 < 5%)
- **クリーンな metrics ≥ 50 本** (= Phase 2 の validator を通過 + 24h 以上経過した posts のみカウント)
- 各軸の値ごとに **最低 5 サンプル** はある (= hook_type が 5 種類なら計 25 本以上)

### 出口 KPI

- A/B 検定: ベースライン群 vs 改善群 (= バンディット選択) で完視聴率 (or save rate) に有意差 (p < 0.05)
- 改善群が **ベースラインを有意に上回る**

### タスク

#### B-3.1 集計 view

```sql
CREATE VIEW v_axis_performance AS
SELECT
  s.hook_type, s.tone, s.dominant_emotion, s.theme,
  COUNT(*) as n,
  AVG(pm.views) as avg_views,
  AVG(pm.completion_rate) as avg_completion,
  AVG(pm.save_rate) as avg_save
FROM screenplays s
JOIN videos v ON v.screenplay_id = s.id
JOIN posts p ON p.video_id = v.id
JOIN (SELECT post_id, MAX(fetched_at), * FROM post_metrics
      WHERE fetched_at > datetime('now','-24 hours') GROUP BY post_id) pm
  ON pm.post_id = p.id
GROUP BY s.hook_type, s.tone, s.dominant_emotion, s.theme;
```

軸の組み合わせは爆発するので、**1 軸ずつ独立に** 集計し、後で重ねる方針。

#### D-3.2 バンディット選択器

`improvement/bandit.py`:

```python
class EpsilonGreedyBandit:
    """
    epsilon=0.2 で 20% は random exploration、80% は historical best。
    軸 (= hook_type 等) ごとに独立した instance を持つ。
    """
    def select(self, axis: str) -> str: ...
    def record(self, axis: str, value: str, reward: float): ...
```

Phase 3 序盤は ε-greedy で十分。サンプル ≥ 200 になったら Thompson sampling に移行する選択肢を残す。

#### D-3.3 prompt injection

`analyze/compose.py` または新規 `improvement/prompt_injector.py` で、analyze pipeline の Claude system prompt に追記:

```
過去の高パフォーマンス傾向 (24h 完視聴率 中央値):
- hook_type: 共感型 (35.2%) > 結論先出し (28.1%) > 問題提起 (24.5%)
- tone: フラット (32.0%) > エモーショナル (29.3%)

ただし exploration として今回は意図的に "問題提起 + エモーショナル" を試す。
```

実装上のポイント: **常に "今回はこの軸でこの値を試す" を明示** して、Claude に「無難な選択」をさせず exploration を強制する。

#### B-3.4 experiment_assignments テーブル

```sql
CREATE TABLE experiment_assignments (
  id INTEGER PRIMARY KEY,
  video_id INTEGER NOT NULL,
  axis TEXT NOT NULL,                          -- "hook_type"
  selected_value TEXT NOT NULL,                -- "問題提起"
  strategy TEXT NOT NULL,                      -- "epsilon_greedy_explore" / "epsilon_greedy_exploit" / "baseline"
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

これで「どの選択がどの動画に効いたか」を後で追える。

#### D-3.5 A/B 切替

`config.IMPROVEMENT_STRATEGY` を 3 値で切る:

- `"baseline"` — Phase 2 までの挙動 (= バンディット無し)
- `"shadow"` — バンディットの選択は記録するが、実際の生成には反映しない (= 影響評価)
- `"active"` — バンディットの選択を反映

最初の 2 週は `"shadow"` で動かして、その後 `"active"` に切り替えて A/B 検定。

### ロールバック

`config.IMPROVEMENT_STRATEGY="baseline"` で Phase 2 状態に戻る。実験用 SQLite テーブルは残しておけば過去データを失わない。

---

## 6. Phase 4: 本番展開 (任意 / 後日判断)

### 目的

実験用アカウントから本番アカウントへ。

### 出口 KPI (例)

- 本番アカウントで 1 ヶ月、品質クレームゼロ、人間レビュー率 < 10%、収益化基準達成

### タスク

- 本番公開フローに **人間 gate を残す or 完全自動** を選択 (= ここはビジネス判断)
- 監査ログ: 全公開動画の `generation_records` を凍結保存 (= 後でクレーム対応や規約変更時の追跡)
- rollback 手順: YouTube からの取り下げ + IG/TikTok の削除 を 1 コマンド化

---

## 7. データスキーマ統合図

```
reference_videos  (拡張: source_url, fetched_at, license_status)
       │
       │ 1:N (1 参考動画から複数 screenplay 派生もありうる)
       ▼
   screenplays  (既存: hook_type, tone, dominant_emotion, theme, character_archetype の自動タグ)
       │
       │ 1:N
       ▼
     videos  ─────────── 1:1 ─────────── generation_records  (新設)
       │                                      │
       │                                      ├─ stage_runs (JSON)
       │                                      ├─ prompts (JSON)
       │                                      ├─ seeds (JSON)
       │                                      ├─ validator_scores (JSON, Phase 2 で埋める)
       │                                      └─ total_cost_usd
       │
       │ 1:1 ─────── 1:N ────── qa_failures  (新設)
       │
       │ 1:N
       ▼
     posts ────────── 1:N ────── post_metrics
       │
       │ 1:N
       ▼
   experiment_assignments  (Phase 3 新設)
```

---

## 8. 観測 / 退路 / 安全装置 (横断)

| 装置           | 実装                                                       | 発火条件                                |
| -------------- | ---------------------------------------------------------- | --------------------------------------- |
| kill-switch    | env `DISABLE_AUTO_LOOP=1` を `auto_loop.py` 冒頭で確認     | 手動                                    |
| daily cap      | env `DAILY_COST_CAP_USD=20` / `DAILY_VIDEO_CAP=5`          | 当日合計超過                            |
| monthly budget | env `MONTHLY_COST_CAP_USD=300`                             | 当月合計超過                            |
| failure budget | 直近 N 本の失敗率がしきい値超 (例: 直近 5 本中 3 失敗)     | 自動で auto-disable + Slack             |
| 公開先強制     | env `AUTO_LOOP_ALLOW_PUBLIC=0` (Phase 4 まで 0 固定)       | 常時                                    |
| Slack 通知     | env `SLACK_WEBHOOK_URL`                                    | 各 stage 失敗 / cap 抵触 / disable 発火 |
| 監査ログ       | `generation_records` + `experiment_assignments` の凍結保存 | 公開ごと                                |

---

## 9. 直近 1 週間の着手手順 (= 最初の Phase 0)

| 日    | タスク                                                                                                                        | 受け入れ基準                                                                        |
| ----- | ----------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Day 1 | `analytics/schema.sql` に generation_records / qa_failures / reference_videos.\* 追加 + マイグレーションスクリプト            | `python3 scripts/migrate.py` でエラー無く適用                                       |
| Day 2 | `preview_server.py` に `POST /api/projects/<TS>/reject` エンドポイント新設 + UI ボタン (= StageOverlay や各 stage page)       | 手動で curl して artifact が `data/qa_failures/` にコピーされる                     |
| Day 3 | UI 側 reject ボタン + カテゴリ enum チェックボックス + note 欄。frontend `npm run build` まで                                 | UI から reject すると DB の `qa_failures` に行が増える                              |
| Day 4 | 各 stage 完了時に `generation_records.stage_runs` に記録するフックを `staged_pipeline/` 各 module に挿入                      | 1 動画分流して全 stage の record が残る                                             |
| Day 5 | regenerate 時の自動アーカイブ (= 既存 regenerate ハンドラに 5 行追加)                                                         | UI から regenerate すると前世代が `qa_failures/?source=regenerate_implicit/` に残る |
| Day 6 | env `DISABLE_AUTO_LOOP` の gate を `main.py` 冒頭に追加 (Phase 0 では未使用だが先回り)                                        | 環境変数で `python3 main.py` が即 exit する                                         |
| Day 7 | 手動運用で 2-3 本作って qa_failures に流れることを実機確認 + Phase 0 KPI ダッシュボード (= Streamlit に Phase 進捗パネル追加) | qa_failures に最低 1 件、generation_records に 2-3 件入っていることを目視確認       |

---

## 10. 主要リスクと落とし穴

| リスク                          | 兆候                                                   | 対処                                                                            |
| ------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------- |
| Phase 0 が永遠に終わらない      | 「もう少し手動でデータ集めたい」が続く                 | 不良 10 件 + 正常 10 件で機械的に Phase 1 に進む規則を最初に決める              |
| validator のしきい値が厳しすぎ  | Phase 2 で auto_rejected が量産されて publish 数が激減 | 週次の `eval_validators.py` で適合率 < 70% の validator は緩める                |
| Phase 3 で exploration が枯れる | 同じ hook_type ばかり選ばれる                          | ε ≥ 0.2 を最低保証 + axis 単位で「最低 N 本に 1 本は random exploration」を強制 |
| シグナル汚染                    | Phase 2 が未完成のまま Phase 3 に進む                  | Phase 3 入口条件の **クリーンな metrics ≥ 50 本** を厳格に守る                  |
| YouTube quota 403               | 連日 publish が 403 で止まる                           | `platform_clients/youtube.py:280` に 403 catch + 翌日キュー化                   |
| Sync.so 20MB 超過               | lipsync が無音化                                       | scene 動画を投入前に bitrate チェック + 必要なら再エンコード                    |
| 著作権                          | 参考動画を無許諾で多量 DL                              | reference_videos.license_status を必須化、`unconfirmed` は analyze に進めない   |
| アカウント信用毀損              | 不良動画を本番アカウントに公開                         | Phase 4 まで unlisted 強制。env による gate を二重化                            |
| コスト暴走                      | 1 日で予算超過                                         | daily/monthly cap + Slack alert                                                 |

---

## まとめ

要点:

1. **Phase 0 (計測基盤) → Phase 1 (open-loop) → Phase 2 (QA) → Phase 3 (closed-loop) → Phase 4 (本番展開)** の順序を厳守する
2. 各 Phase は **数値 KPI** で出口を規定し、満たすまで次に進まない
3. 計測基盤を最優先で入れることで、後の Phase 2/3 が「過去データ込みで」設計できる
4. 公開先は Phase 3 まで **unlisted / 実験アカウント** に強制
5. 改善ロジック (Phase 3) は **shadow → active** の二段階で投入

着手は **Day 1-7 の Phase 0 タスク** から。
