# 組み合わせ identity + 報酬学習による Cache 進化計画

本ドキュメントは「現状の SHA-256 完全一致 cache が auto_loop 経路でほぼ機能しない問題」を直視し、生成物 cache を **「Atomic 素材集合 / 組み合わせ identity / 投稿後報酬学習」の 3 層** に再構成する設計提案を残す。Phase 0〜4 (= `2026-05-07_full-automation-implementation-plan.md`) の上に追加で乗せる Phase X 系列として位置付ける。

実装着手前の **設計議論ドキュメント**。タスクは checklist で残すが、まだ未着手。

---

## 0. TL;DR

- 現状の cache は `(prompt 文字列, character_refs sha, location_ref sha, model id)` の **4 要素 SHA 完全一致**。auto_loop は `prompt` を Claude が free-form で生成するため一致せず、**hit 率は実用上ほぼ 0%**。bg miss は kling の上流条件 (= bg image sha) を巻き込んで kling も連鎖 miss する。
- 解決方向は 2 つあり、**(A) 完成品 cache を semantic 検索で緩める案は危険** (= 同じ被写体・同じ場面・同じ動作の組み合わせが揃わないと「全然違う動画」が混ざる)。**(B) 上流の prompt を SSOT 集合化して SHA 完全一致を成立させる案** が現行設計と整合する。
- 提案はコア 1 つ: **prompt を含む全ての scene 構成要素を atomic asset の id 参照に置き換え、cache の SHA は集合の組み合わせから決定論的に派生する形にする**。これに **投稿後 metrics 由来の報酬** を組み合わせると、フィードバックループで「効く組み合わせ」が学習される。
- 量産前 (0 本時点) に Phase X-1 / X-2 (= meta 拡張 + 集合 SSOT 新設) だけ仕込んでおけば、X-3 以降は 30〜100 本溜まってから後付けで載せられる。

---

## 1. 背景と現状

### 1.1 現状の cache 仕様

| 対象 | 実装                | キー構成                                                                                                    |
| ---- | ------------------- | ----------------------------------------------------------------------------------------------------------- |
| 背景 | `bg_cache.py:115`   | `(prompt: 完全文字列, ref_shas: character_refs 各画像の sha, loc_sha: location JSON sha, model: imagen id)` |
| 動画 | `kling_cache.py:81` | `(augmented_animation_prompt, kling_duration, bg_image_sha, model_id, aspect_ratio, cache_version)`         |

`bg_cache.compute_bg_cache_key` の `prompt` は `_build_background_prompt(scene, screenplay)` の戻り値で、scene 単位の自由テキスト `background_prompt` をベースにロケ情報を先頭注入した最終プロンプトの **完全文字列**。1 文字でも違えば SHA は変わる。

`kling_cache.build_cache_key` の `bg_image_sha` は **bg cache 出力 PNG の画素データ sha**。bg cache が miss して新しい画像を生成すれば必ず変わる = kling 上流条件が破綻する。

### 1.2 auto_loop で hit しない理由

cache key 4 要素を、手動運用と auto_loop で比較:

| 要素               | 手動 (= 既存 screenplay 再走)           | auto_loop (= 参考動画ごとに analyze)                 |
| ---------------- | --------------------------------- | --------------------------------------------- |
| `model`          | 固定                                | 固定                                            |
| `loc_sha`        | screenplay の `location_ref` で固定   | analyze pipeline 次第。既存 id を選ばせれば一致、新規提案を許せば乱立 |
| `ref_shas`       | screenplay の `character_refs` で固定 | 同上                                            |
| **`prompt` 文字列** | **手書きの固定文字列** → 再走で完全一致           | **Claude が毎回新しい言い回しで生成** → 一致しない              |

具体例: 「home_office で f1\_\_office が驚く」というセマンティクス的に同じ scene でも、

| 動画 | location_ref | character_refs | background_prompt (Claude 出力)           | SHA       |
| ---- | ------------ | -------------- | ----------------------------------------- | --------- |
| A    | home_office  | f1\_\_office   | `デスクで PC を覗き込み驚いた表情`        | X         |
| B    | home_office  | f1\_\_office   | `PC の画面を見つめ目を丸くする`           | **Y ≠ X** |
| C    | home_office  | f1\_\_office   | `ノートPC を覗き込み驚愕の表情を浮かべる` | **Z ≠ X** |

ロケ + キャラの 2 要素は一致しているが、`prompt` 文字列が言い換えで変わるため 4 要素 sha は別物になる。これが Claude の出力ブレに起因する **構造的 cache miss**。

### 1.3 完成品 cache を semantic 検索で緩める案は危険

「prompt の完全一致を諦め、意味類似で近傍検索して再利用すればいい」発想は一見コスト効率が良いが、bg PNG / kling MP4 は **装飾 / 光 / 配色 / 小物 / 被写体 / ポーズ / カメラ距離 / 動作** を 1 ファイルに焼き付けた完成品で、

- 動作が違う完成品を流用 → セリフと動作が乖離した動画になる
- 被写体が違う完成品を流用 → 別人が混ざる
- bg を意味類似で差し替えた瞬間、kling は bg image sha 依存で必ず miss → kling は再生成

つまり完成品の意味検索は (a) 上流で品質崩壊するか (b) 下流で hit しないかのどちらかで、cache 効率は意外と上がらない。**現行の "完全一致 cache" 設計はそれ自体は正しい**。

### 1.4 残された方向

cache hit を増やす道は構造上 2 つしかない:

| 案   | 内容                                                                               | 評価                                                                             |
| --- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| (A) | 完成品 cache を semantic 検索で緩める                                                      | 品質崩壊リスク高 / kling 連鎖 miss で効率低 / **採用しない**                                      |
| (B) | **上流の prompt を SSOT 集合化し、scene を atomic asset の組み合わせとして表現** → SHA 完全一致を構造的に発生させる | 既存 `locations/` `characters/` SSOT 思想と一貫 / Phase 3 bandit のレールに乗せられる / **本提案** |

---

## 2. 設計提案: 3 層分離

scene の表現を **「素材 / 組み合わせ / 実績」** の 3 層に分け、各層の責務を独立させる。

```
Layer 3  Performance       (post_metrics 24h/7d, validator_score, human_reject)
                                ↑ 各組み合わせに紐付く実績
Layer 2  Composition       (location, character, action, hook, arc, emotion) tuple
                                ↑ scene = atomic assets の組み合わせ
Layer 1  Atomic Assets     locations/  characters/  actions/  hooks/  arcs/
                                ↑ 全部 SSOT、絞られた集合
```

### 2.1 Layer 1: Atomic Assets

既存 SSOT に 3 つの集合を追加する:

| ディレクトリ          | 状態     | 中身                                                                             | 例                                                  |
| --------------------- | -------- | -------------------------------------------------------------------------------- | --------------------------------------------------- |
| `locations/<id>.json` | 既存     | decor / lighting / color_palette / props / camera_distance                       | `home_office`, `cafe_window`, `office_desk`         |
| `characters/<base>/`  | 既存     | base + wardrobe variants + voice.json                                            | `f1`, `f1__office`, `m1__suit`                      |
| `actions/<id>.json`   | **新規** | 動作テンプレ + animation_prompt スニペット + 推奨 emotion + 推奨 camera_distance | `surprise_pc`, `decisive_stand`, `lean_back_relief` |
| `hooks/<id>.json`     | **新規** | 動画冒頭 1〜3 秒のフックパターン + scene 構成テンプレ                            | `paradox_q`, `shock_number`, `failure_confess`      |
| `arcs/<id>.json`      | **新規** | シーン進行の感情変化テンプレ (= 5〜7 シーン分の emotion 列)                      | `low_to_high`, `confusion_to_resolve`               |

各 atomic は **手書きで初期 5〜10 個** に絞る。集合が小さいことが本提案の根幹であり、自動拡張は X-5 以降で扱う。

#### actions スキーマ案

```json
{
  "id": "surprise_pc",
  "label": "PCを覗き込み驚愕",
  "animation_prompt": "subject leans forward to laptop screen, eyes widen, hand to mouth",
  "recommended_emotion": "驚き",
  "recommended_camera_distance": "medium-close",
  "compatible_locations": ["home_office", "office_desk", "cafe_window"],
  "duration_bucket_sec": 5
}
```

#### hooks スキーマ案

```json
{
  "id": "paradox_q",
  "label": "逆説提示型",
  "first_scene_template": {
    "action_id": "surprise_pc",
    "line_pattern": "{逆説的な問いかけ}",
    "emotion": "驚き"
  },
  "follow_arc_id_candidates": ["low_to_high", "confusion_to_resolve"]
}
```

スキーマは 2 例のみ概念提示。詳細フィールドは X-2 着手時に詰める。

### 2.2 Layer 2: Composition Identity

scene の identity を **atomic asset id の tuple** として定義する:

```python
composition_id = sha256_short(
    location_id, character_id, action_id, hook_id, emotion, camera_distance,
)
```

これを `bg_cache.store` / `kling_cache.store` の meta に追加で書き込む。**既存 cache key (= prompt SHA) は破壊しない** で並走させる。lookup は:

1. 既存の prompt SHA 完全一致 lookup (= back-compat)
2. miss なら composition_id 単位での近傍 lookup (= 同 composition の過去エントリ)
3. miss なら新規生成

着地点として、X-2 で analyze pipeline を「id 選択方式」に変更すると、`background_prompt` も atomic id から決定論的に組み立てられるようになり、**1 と 2 は実質同じになる** (= prompt 完全一致と composition 一致が一致する)。

### 2.3 Layer 3: Performance Score

Phase 3 の `experiment_assignments` テーブルを **scene 粒度** に拡張する:

```
experiment_assignments
  generation_id (= TS)
  scene_idx     ← 追加
  axis_name     (location | character | action | hook | arc | emotion)
  value_id      (= atomic asset の id)
  composition_id ← 追加
```

新規 view `v_composition_performance`:

```sql
SELECT
  composition_id,
  location_id, character_id, action_id, hook_id,
  COUNT(*) AS n_videos,
  AVG(completion_rate_24h) AS avg_completion,
  AVG(engagement_rate_24h) AS avg_engagement,
  AVG(retention_at_3s)     AS avg_hook_retention
FROM experiment_assignments ea
JOIN posts p USING (generation_id)
JOIN post_metrics pm USING (post_id)
WHERE pm.fetched_at >= p.published_at + INTERVAL 24 HOUR
GROUP BY composition_id, location_id, character_id, action_id, hook_id
HAVING n_videos >= 3;
```

`improvement/prompt_injector.py` (= 既存) がこの view を読み、analyze pipeline の `instructions` に「`home_office × decisive_stand` の median completion は 42%、これを優先せよ」を注入する。

---

## 3. フィードバックループの動作

X-4 完成後の 1 サイクル:

```
動画 A 生成 (auto_loop)
  └ 組み合わせ: (home_office, f1__office, surprise_pc, paradox_q, low_to_high)
  └ analyze pipeline が atomic id を選択
  └ experiment_assignments に scene 単位で記録
  └ Stage 8 で YouTube 投稿、video_id 取得

24h 後 (cron: scripts/fetch_metrics.py)
  └ post_metrics に completion_rate=35%, engagement=1.2% 記録
  └ experiment_assignments と join → 各組み合わせに reward が付く

動画 B 生成 (auto_loop)
  └ improvement_strategy.select_assignments_for_video(seed=...)
       → bandit が v_composition_performance を読んで:
         "home_office × surprise_pc の avg_completion は 28%,
          home_office × decisive_stand は 42%" → decisive_stand を優先
  └ analyze pipeline に "action_id=decisive_stand を使え" を注入
  └ scene が決まる → composition_id が決まる → cache lookup hit (= 過去動画と同じ tuple)
  └ bg / kling は cache から取り出して API 呼び出しゼロ
```

「**生成 → 投稿 → 計測 → 学習 → 次の生成に反映**」が scene 粒度で閉じる。

---

## 4. 既存資産との接続

Phase 0〜4 で構築済みの基盤との対応:

| 役割             | 既存 (= 再利用)                                               | 本提案で追加するもの                                   |
| ---------------- | ------------------------------------------------------------- | ------------------------------------------------------ |
| atomic 集合      | `locations/`, `characters/`                                   | `actions/`, `hooks/`, `arcs/`                          |
| 組み合わせ記録   | `experiment_assignments` (= 動画粒度)                         | scene 粒度に拡張、`composition_id` 列追加              |
| 実績集計         | `v_axis_performance` view                                     | `v_composition_performance` view                       |
| 学習             | `improvement/bandit.py` (ε-greedy)                            | (拡張不要、軸候補を増やすだけ)                         |
| prompt 注入      | `improvement/prompt_injector.py`                              | scene 粒度の指示を吐く形に拡張                         |
| 投稿後計測       | `scripts/fetch_metrics.py` + `post_metrics` テーブル          | (そのまま)                                             |
| cache            | `bg_cache.py`, `kling_cache.py` (SHA 完全一致)                | meta に `composition_id` 追加 (= 破壊的変更なし、並走) |
| analyze pipeline | `scripts/analyze_video.py` (= Claude Opus 4.7 で抽象台本生成) | atomic id 選択方式への切替 (= 自由テキスト生成を縮退)  |

新規追加は **3 ディレクトリ + 1 view + meta フィールド + analyze prompt の制約**。Phase 3 のレールに乗るので大半は既存コードの拡張で済む。

---

## 5. 段階的実装

5 つの Phase に分け、各々に **入口条件 / 出口 KPI / タスク / ロールバック** を持たせる。

| Phase | 内容                                          | 必要データ量 | 着手目安                 |
| ----- | --------------------------------------------- | ------------ | ------------------------ |
| X-1   | cache meta 拡張 + experiment_assignments 拡張 | 0 本         | 量産開始前               |
| X-2   | atomic SSOT 新設 + analyze pipeline 切替      | 0 本         | 量産開始前               |
| X-3   | scene 粒度の bandit + view                    | 30+ 本       | 量産開始から数週間後     |
| X-4   | 報酬学習 prompt 注入の本接続                  | 100+ 本      | 量産開始から 1〜2 ヶ月後 |
| X-5   | atomic 集合の自動拡張                         | 300+ 本      | (任意)                   |

### 5.1 Phase X-1: Composition meta 配線 (量産前 / 0 本)

#### 入口条件

Phase 4 まで完了 (= 現状)。

#### 出口 KPI

- `bg_cache` / `kling_cache` の meta に `composition_id` フィールドが書き込まれる
- `experiment_assignments` テーブルに `scene_idx` / `composition_id` 列がマイグレーション済み
- 既存 cache lookup は破壊されていない (= back-compat 確認済み)

#### タスク

- [ ] `bg_cache.py:_build_bg_cache_meta` に `composition_id` (= 現状は仮の hash でも可) を追加
- [ ] `kling_cache.py:_build_kling_cache_meta` も同様
- [ ] `analytics/db.py` にマイグレーション v7: `experiment_assignments` に `scene_idx`, `composition_id` 列追加
- [ ] `improvement/strategy.py:record_assignments` の signature を scene 粒度に拡張 (= 旧 signature は wrap で残す)
- [ ] テスト: `tests/test_bg_cache_composition_id.py` / `tests/test_kling_cache_composition_id.py` / `tests/test_analytics_db_phase_x1.py`

#### ロールバック

- `composition_id` 列は nullable で追加 → 旧コードは無視できる
- meta フィールドの追加は読み出し側が optional で扱えば後方互換

### 5.2 Phase X-2: Atomic SSOT 新設 + analyze 切替 (量産前 / 0 本)

#### 入口条件

X-1 完了。

#### 出口 KPI

- `actions/`, `hooks/`, `arcs/` ディレクトリに **手書きで各 5〜10 個** の id が存在 (= JSON + 必要なら preview)
- `scripts/analyze_video.py` の Claude system prompt が「`actions/` `hooks/` `arcs/` の既存集合から選べ」と縛る形に変更されている
- 単体テスト: 同じ参考動画 + 同じ seed で analyze を 2 回回し、出力 `(location_id, character_id, action_id, hook_id, arc_id)` の tuple が **一致する** (= prompt 文字列 free-form 部分が消えている確認)

#### タスク

- [ ] `actions/<id>.json` スキーマを `docs/abstract-screenplay-design.md` に追記
- [ ] `actions/` に手書き 5〜10 個 (`surprise_pc`, `decisive_stand`, `lean_back_relief`, `confused_search`, `triumph_pose` 等)
- [ ] `hooks/<id>.json` 同様 5〜10 個 (`paradox_q`, `shock_number`, `failure_confess`, `before_after`, `direct_addr`)
- [ ] `arcs/<id>.json` 同様 3〜5 個 (`low_to_high`, `confusion_to_resolve`, `failure_to_pivot`)
- [ ] `scripts/analyze_video.py` の Claude prompt を変更 (= 既存集合から id を選ぶ output schema を強制)
- [ ] `scene_gen._build_background_prompt` / `_augment_animation_prompt` を atomic id ベースの組み立てに切替 (= free-form 文字列を排除)
- [ ] テスト: analyze 出力の決定性確認、scene_gen の id 解決テスト
- [ ] CLAUDE.md の台本 JSON スキーマセクションを更新 (= `action_id`, `hook_id` 等の新フィールド)

#### ロールバック

- 旧 `background_prompt` / `animation_prompt` フィールドは残し、新 atomic id が無いシーンでは旧経路を使う形で互換維持
- atomic 集合の品質が悪ければ id を増やすだけで対応可能

### 5.3 Phase X-3: scene 粒度の bandit + view (30+ 本)

#### 入口条件

- X-2 完了
- auto_loop で **30 本以上の動画** が generation_records / experiment_assignments に積まれている
- 各動画が YouTube 投稿済みで post_metrics の 24h 値が取れている

#### 出口 KPI

- `v_composition_performance` view が稼働、`HAVING n_videos >= 3` で意味のあるエントリが **5+ tuple** ある
- bandit が scene 単位で軸選択する経路が動作 (= shadow mode で 1 週間記録のみ)

#### タスク

- [ ] `analytics/db.py` v8: `v_composition_performance` view 作成
- [ ] `improvement/axis_performance.py` に `query_composition_performance` を追加
- [ ] `improvement/strategy.py` で scene 単位の選択を `IMPROVEMENT_STRATEGY=composition_shadow` で記録のみ実行
- [ ] テスト: view クエリの fixture テスト、shadow record の整合性

#### ロールバック

- shadow mode は記録のみ → prompt 注入には影響しない、いつでも止められる

### 5.4 Phase X-4: 報酬学習 prompt 注入 (100+ 本)

#### 入口条件

- X-3 が shadow mode で **2 週間以上稼働** し、`v_composition_performance` に統計的に意味のあるエントリが 20+ tuple
- shadow と active の reward 期待値の差を A/B 検定計画として固めている

#### 出口 KPI

- `IMPROVEMENT_STRATEGY=composition_active` で 1 ヶ月稼働
- ベースライン (= 旧 axis 粒度の improvement_strategy=active) に対し、completion_rate +5% 以上 (p<0.1) を達成

#### タスク

- [ ] `improvement/prompt_injector.py` を scene 粒度の指示を出すように拡張 (= "scene N では action_id=X を優先" 形式)
- [ ] auto_loop の `_run_analyze` への instructions 構築を scene 粒度対応に
- [ ] A/B 切替フラグ `IMPROVEMENT_STRATEGY` の値を追加: `composition_shadow` / `composition_active`
- [ ] `scripts/dashboard.py` に composition 別 reward の可視化を追加

#### ロールバック

- フラグを `baseline` に戻すだけで影響を切れる
- shadow に戻して観測のみに退避可能

### 5.5 Phase X-5: atomic 集合の自動拡張 (任意 / 300+ 本)

#### 目的

手書き SSOT を超えて、観測された高 reward 組み合わせから **新 atomic id を AI 提案** する経路を作る (= 多様性と効率の両立)。

#### タスク (= 概念のみ、データ蓄積後に詳細化)

- [ ] 高 reward な未登録組み合わせをクラスタリング (= 視聴者の好みに合うが現集合に無いもの)
- [ ] Claude / 人間レビューで新 atomic id 候補を生成
- [ ] 集合への組み込みは **人間 gate** を通す (= 自動追加は禁止、品質基準を逸脱するため)

---

## 6. トレードオフ

| 軸                     | 集合化 / 学習寄り (= 本提案)     | 自由生成寄り (= 現状)        |
| --------------------- | ---------------------- | -------------------- |
| 創造性                   | 5〜10 個に縛られる → 飽きやすい    | Claude の自由度が高い → 個別性 |
| cache hit 率           | 高 (= 完全一致が頻発)          | 低 (= ほぼ 0%)          |
| 学習可能性                 | 高 (= 同じ tuple が反復試される) | 低 (= 各動画ユニークで集計不能)   |
| 必要データ量                | 100+ 本で報酬学習が動く         | 不要                   |
| analyze pipeline の複雑度 | id 選択のみ (= シンプル)       | 自由テキスト生成 (= 複雑)      |
| 失敗の伝染                 | 悪い tuple が永続化するリスク     | 1 動画で完結              |

**学習収束のリスク** (= 高 reward 組み合わせに過収束する) は bandit の ε (= exploration ratio) で制御する。`composition_active_explore_30` のような変種で「30% は新規組み合わせを試す」を保証する。

**集合のキュレーション負荷**: atomic id を増やすほど組み合わせ爆発する。X-2 開始時は 各 5〜10 個に絞り、X-5 まで自動拡張は許容しない。

---

## 7. 未解決問題

実装着手前に詰めるべき論点:

1. **`background_prompt` の自由度をどこまで許すか**: id 選択方式に振ると Claude の表現力を捨てる。「id 選択 + 軽微な自由テキスト挿入 (= 数十文字以内)」のハイブリッドにすべきか、純粋な id 選択にするかは X-2 着手時に決める。
2. **キャラの感情表現粒度**: 現状の `EMOTION_AUDIO_TAGS` (9 種) と新設 `actions/` の `recommended_emotion` の関係を整理する必要がある。重複が起きる可能性。
3. **既存 screenplay の移行**: 既存 `screenplays/<name>.json` (= 手書き台本) は `action_id` を持たない。X-2 切替時の互換維持戦略 (= 旧 free-form を残しつつ id を任意フィールドにする) を実装で詰める。
4. **post_metrics の取得遅延**: YouTube は 24h 取得可能だが IG/TikTok は半自動 (= CSV 取込)。X-3 以降の reward 計算は YouTube 単独になる可能性が高い。マルチプラットフォームでの reward 統合は X-4 以降で扱う。
5. **scene 単位 reward の付与**: 現状の post_metrics は動画全体の指標 (= completion_rate 等) のみ。scene 単位の reward (= retention_at_3s, drop_off_per_scene) は YouTube Analytics API の audience retention curve から導出する必要があり、実装重め。X-3 の view 設計時に「動画粒度 reward を全 scene に均等配分するのか、retention curve から scene 別に分配するのか」を決定する。

---

## 8. 関連ドキュメント

- `docs/plannings/2026-05-07_full-automation-feasibility.md` — フルオート実現可能性の判定根拠
- `docs/plannings/2026-05-07_full-automation-implementation-plan.md` — Phase 0〜4 全体計画
- `docs/plannings/2026-05-08_phase-3-implementation.md` — bandit + experiment_assignments 実装記録 (= 本提案の前提基盤)
- `docs/abstract-screenplay-design.md` — 抽象台本生成 + compose 合成設計 (= X-2 で更新対象)
- `docs/architecture-decisions.md` — AI モデル選定、コスト構造 (= X-1 着手時に composition cost の節を追記する)
- `CLAUDE.md` — 台本 JSON スキーマ (= X-2 で `action_id` 等の新フィールド追加を反映)

---

## 9. 推奨アクション

**X-1 と X-2 だけ、量産を本格化する前に着手する**。理由:

- データ 0 本でも実装可能 (= 集合の手書きと meta 拡張だけ)
- これを入れずに 20〜30 本量産すると、「組み合わせ単位の reward」が貯まらず、後から振り返れない (= 分析できない動画群が量産される)
- X-3 以降は **量産が走り出してから後付けで載せられる**

逆に X-1/X-2 抜きで量産すると、cache key 構成は今のままなので auto_loop の hit 率は 0% に貼り付き、Phase 3 の bandit 学習も動画レベルに留まる。X-3 以降の閉ループ価値が出ない。

X-1 / X-2 の見積もり工数感 (= 着手判断のため):

| Phase | 想定工数感           | 主リスク                                                         |
| ----- | -------------------- | ---------------------------------------------------------------- |
| X-1   | 1〜2 日 (= 配線中心) | back-compat の取り扱いミス (= マイグレーション v7 の慎重設計)    |
| X-2   | 3〜5 日              | atomic 集合の手書きキュレーション品質、analyze prompt 切替テスト |

X-1 + X-2 で 1 週間程度。これを Phase 4 マージ後の現時点でやり切ってから auto_loop の本格量産を始めるのが、最も後悔の少ない順序になる。
