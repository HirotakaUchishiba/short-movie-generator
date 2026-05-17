# 包括的リファクタリング計画 (全体最適視点)

最終更新: 2026-05-17
ステータス: ドラフト (= 着手前)

---

## 0. 背景・目的

本ドキュメントは short_movie_generator を **全体最適の視点** で精査し、現時点で抱えている技術的負債を網羅的にリストアップする。一気にやり切ることが目的ではなく、Phase 別 / 優先度別に消化可能なチェックリストを用意し、新規実装 / 機能追加と並走しながら段階的に解消することを目指す。

### スコープ

- Python パイプライン中核 (8 stage + analyze + analytics + final_import + platform_clients)
- 外部 API クライアント層 (elevenlabs / imagen / fal_video / fal_runner / lipsync / video_analyzer / gemini_rewriter)
- HTTP API (preview_server + routes/)
- フロントエンド (React + TypeScript)
- scripts/ + config / tests

### 進行ルール

- `docs/developments/coding-rules.md` §1 「要求された変更だけを行う」を順守。本計画自体は **着手を強制しない** 一覧。各項目は独立 PR で消化する
- `docs/developments/testing.md` §10 「既存テストとの整合性 — 一気にリファクタしない」を順守。grandfathered な既存テストは触らず、新規・隣接修正でついでに寄せる
- CLAUDE.md 「コストのかかる操作を安易に実行しない」を順守。本計画の検証で動画 / 背景 / TTS / lipsync を **再生成しない**

---

## 1. サマリ

| 優先度       | 件数 | 主な内訳                                                                                                                                                   |
| ------------ | ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Critical** | 4    | 公開済み API key 漏洩リスク / SQL injection 余地 / 重複コード乖離リスク / private 直叩き                                                                   |
| **High**     | 24   | 大型モジュール分割 / 共通基盤抽出 / responses 形式統一 / Error Boundary 欠如 / migration 戦略 / publish-analytics 不整合の検知欠如 / 設計 doc 鮮度の drift |
| **Medium**   | 18   | マジックナンバー / f-string ログ / 廃止 script 残骸 / factories/ 未利用 / スキーマ不一致                                                                   |
| **Low**      | 6    | コメント精度 / 命名小揺れ / a11y                                                                                                                           |

**最大の構造的負債:**

1. **`scene_gen.py` 2671 行 / 87 関数** — BG / Kling / TTS / scene 合成の 4 責務が 1 ファイルに同居。`stages/` ディレクトリは作られているが、まだ 2 ファイル (`emotion.py` / `text_utils.py`) だけで切り出し未進行
2. **`preview_server.py` 1544 行** — `routes/` への Blueprint 移行が進行中 (10 Blueprint 抽出済み) だが、`api_error` (= 統一) と `jsonify({"error": ...})` (= 74 箇所) が混在
3. **`ScriptEditPanel.tsx` 1651 行** — 9 useState + 4 責務 (caption / scene grid / boundary / 話者マッピング) が同居
4. **外部 API クライアント 7 個** — retry / backoff / exception hierarchy / client pooling / timeout が **完全に非統一**。共通基盤無し

---

## 2. Critical (= 早急に対処すべき)

### 2.1 `lipsync_client.py` の JSON レスポンス防御性

**現状:**

- `lipsync_client.py:59`: `body = r.json()` の後、`body.get("id")` で dict 前提。レスポンスが list / null だと `AttributeError` がそのまま caller に漏れる
- `lipsync_client.py:84`: `body = r.json() or {}` (= こちらは null fallback あり)

**修正案:**

- `r.json()` を try/except で wrap し、`LipsyncClientError("invalid JSON: ...")` に正規化
- `body` が dict でなければ早期に `LipsyncClientError`
- 同パターンを `elevenlabs_client.py:195` の `data["audio_base64"]` 直接アクセスにも適用

**Why Critical:** Sync.so の障害時に Stage 5 が AttributeError で fail する。`LipsyncClientError` でなければ caller (stage runner) の error classification が機能せず、retry / mark_stage_failed の経路が乱れる。

- [ ] `lipsync_client.py:59,84` を `try / except (ValueError, AttributeError)` で wrap
- [ ] `elevenlabs_client.py:195` 周辺の `dict[key]` を `.get()` + 存在確認に
- [ ] 同観点で `gemini_dialogue_rewriter.py` / `video_analyzer.py` の response parser も点検

### 2.2 API レスポンスボディの log 漏洩

**現状:**

- `elevenlabs_client.py:78-79`: `logger.error("body: %s", last_body[:500])` — レスポンス本文を log 出力
- `lipsync_client.py:57,82`: `f"Sync.so generate 作成失敗 ({r.status_code}): {r.text[:300]}"` — `r.text` を例外メッセージに同梱

**修正案:**

- `r.text` / response body の log / exception message 同梱は廃止 or sanitize 後に限定
- 必要なら別経路で `tmp/<TS>/debug/` に dump し、debug log に path だけ残す

**Why Critical:** ElevenLabs / Sync.so のエラーレスポンスにユーザー入力 (= line.text, screenplay 全文) や API key の一部が含まれて返るケースがある (= ベンダーの実装に依存)。log 集約 / 共有時にこれが流れると `coding-rules.md` §9 違反。

- [ ] `elevenlabs_client.py:78-79,91` の `last_body` ログを削除 or hash 化
- [ ] `lipsync_client.py:57,82,97-98` の `r.text` 同梱を削除 or `r.status_code` のみに
- [ ] 同パターンを `fal_video_client.py` / `imagen_client.py` でも grep

### 2.3 `analytics/db.py` の f-string SQL 構築

**現状:**

- `analytics/db.py:151,153`: `f"PRAGMA table_info({table})"` / `f"ALTER TABLE {table} ADD COLUMN {ddl}"`
- `analytics/db.py:686-687`: `f"INSERT INTO generation_records ({cols_sql}) VALUES ..."`
- `analytics/db.py:893-894,918-919`: `f"SELECT axis_value, {metric} AS metric, n FROM {view}"`

**現在の防御:** 呼び出し側で whitelist (`_GEN_REC_*_FIELDS` / metric / view の enum) を持っているため、現時点で injection 経路はない。

**Why Critical (= 慣習として):**

- 防御が「呼び出し側の whitelist 順守」に依存しており、将来 caller が増えたときに見落としやすい
- `coding-rules.md` は f-string SQL を明示禁止していないが、防御線が分散しているのは保守性の地雷

**修正案:**

- table / column / view 名はモジュール内の `_ALLOWED_TABLES` 等の定数 set で **関数内 assert** する
- value 部分は `?` placeholder で parameterize (= 既に大半は対応済み)

- [ ] `analytics/db.py:151,153` の DDL 文字列構築箇所に `assert table in _ALLOWED_TABLES` を入れる
- [ ] `analytics/db.py:686-687` の `cols_sql` は関数の入口で whitelist 検証
- [ ] `analytics/db.py:893-919` の metric / view も同様

### 2.4 `scene_gen.py` の `_build_audios_from_full` / `_build_audios_from_per_voice` 乖離リスク

**現状:**

- `scene_gen.py:1285-1466`: `_build_audios_from_full` (one-shot 経路)
- `scene_gen.py:1468-1688`: `_build_audios_from_per_voice` (per-character 経路)
- 2 関数は docstring で「出力契約は同一」と明記されているが、コードは完全に並走
- `staged_pipeline.py:754` から `_build_audios_from_full` (private) を直接呼び出し

**修正案:**

- 両関数の共通部分 (silenceremove + tail concat + atempo + per-scene concat) を `_build_line_audio_from_segment(start, end, ts_path, ...)` に抽出
- one-shot 経路は full_text 全体から segment を切る driver、per-voice は line.speaker ごとに segment を切る driver として再構成
- `staged_pipeline.py:754` は public wrapper (= `scene_gen.rebuild_audios_after_boundary_change(...)`) を経由するよう変更

**Why Critical:** per-character TTS は 2026-05-17 に投入されたばかり (= `docs/plannings/2026-05-17_per-character-tts.md`)。今後 emotion / acoustic 由来の per-line 調整が増えると、one-shot / per-voice のどちらかにだけ反映されて出力契約が破綻するリスク。テストは `test_build_audios_from_per_voice.py` に集中していて、one-shot 側との parity が保証されていない。

- [ ] `scene_gen.py` に `_extract_line_audio_segment()` 共通ヘルパーを抽出
- [ ] `_build_audios_from_full` / `_build_audios_from_per_voice` を共通ヘルパー経由に refactor
- [ ] `staged_pipeline.py:754` の private 呼び出しを public wrapper 経由に
- [ ] `tests/test_build_audios_parity.py` (新規) で one-shot / per-voice が同 screenplay で同じ per-line ファイル契約を満たすことを検証

---

## 3. High (= 構造的負債、計画的に分解)

### 3.1 大型モジュール分割

#### 3.1.1 `scene_gen.py` 2671 行 → `stages/` 配下に責務分割

**現状:**

- 87 関数 / 2671 行。BG (L80-1020) / Kling (L709-) / TTS audio build (L585-680, L1285-1688) / scene 合成 が同居
- `stages/` ディレクトリは存在するが、まだ `emotion.py` / `text_utils.py` の 2 ファイルだけ

**分割案:**

```
scene_gen.py (薄い orchestrator / 既存 import path を保つ)
  ├ stages/bg.py         ← L80-1020 の BG 生成系 (background prompt 組立 / imagen 呼び出し / bg_cache 連携)
  ├ stages/kling.py      ← L709-, scene_*.trim.mp4 生成
  ├ stages/audio.py      ← L585-680 + L1285-1688 の TTS / per-line / per-scene audio 構築
  ├ stages/scene.py      ← scene_*.mp4 合成 (kling + audio merge + lipsync 呼び出し)
  └ stages/prompts.py    ← _build_background_prompt / _augment_animation_prompt 等
```

**注意点:**

- 一気にやらず、まず **bg.py を切り出し** → 影響範囲確認 → 次に kling.py → audio.py → scene.py の順
- 各分割で `scene_gen.py` には re-export を残し (`coding-rules.md` §1「後方互換のためのシムを残さない」と矛盾するが、テストが多すぎるため例外的に「移行期間中の re-export」とし、最終 PR で全部消す)

- [ ] Phase 2-A: `stages/bg.py` 抽出 (= scene_gen.py:80-1020 のうち bg 専用関数)
- [ ] Phase 2-B: `stages/kling.py` 抽出 (= scene_gen.py:709- の kling 専用関数)
- [ ] Phase 2-C: `stages/audio.py` 抽出 (= 2.4 の Critical 修正と同時に実施)
- [ ] Phase 2-D: `stages/scene.py` 抽出
- [ ] Phase 2-E: `scene_gen.py` を 200 行以下の薄い orchestrator に縮小し、re-export を全部削除

#### 3.1.2 `preview_server.py` 1544 行 → `routes/` への Blueprint 完全移行

**現状:**

- `routes/` に 10 Blueprint 抽出済み (`projects.py` / `stages.py` / `assets.py` / `cost.py` / `clip_library.py` / `intent_*.py` / `final_publish.py` / `config.py` / `_helpers.py`)
- `preview_server.py` には 96 endpoint があり、74 箇所が直接 `jsonify({"error": ...})`、22 箇所が `api_error` を使用
- 移行漏れの大きい塊: analyze job 系 (= `api_cancel_analyze_job` 直後の cache 系 endpoint L953-1287)

**修正案:**

- 残りの endpoint を Blueprint に追い出す (= `routes/analyze.py` / `routes/screenplay.py` 等)
- `api_error()` ヘルパーを全 endpoint で統一 (= 現状 22/96 = 23%)
- `_apply_screenplay_patch()` 汎用ヘルパー導入 (= `api_patch_line` / `api_patch_screenplay_meta` / `api_save_screenplay` の重複 80 行を 1 関数に集約)

- [ ] `routes/analyze.py` (新規) に analyze job 系 endpoint を移動
- [ ] `routes/screenplay.py` (新規) に line patch / screenplay meta patch / save 系を移動
- [ ] `_apply_screenplay_patch()` ヘルパーを `routes/_helpers.py` に追加
- [ ] 残った直接 `jsonify({"error": ...})` をすべて `api_error()` 経由に統一
- [ ] `preview_server.py` を 200 行以下 (= app 初期化と Blueprint 登録だけ) に縮小

#### 3.1.3 `ScriptEditPanel.tsx` 1651 行 → 4 ファイル分割

**分割案:**

```
ScriptEditPanel.tsx (薄い親、Context Provider + 全体レイアウト)
  ├ CaptionEditor.tsx          ← caption / featured_characters / 登場人物 編集
  ├ SceneGridView.tsx          ← scene 一覧 + boundary 操作 (moveLineToScene / addScene / deleteScene)
  ├ SceneEditor.tsx (既存)      ← 各シーンの編集 (= props drilling 解消、Context 経由に)
  └ SpeakerMappingSection.tsx  ← 話者マッピング (analyze 経由 project 専用)
```

**Context 化:**

- 現状: SceneEditor が 12 props を受け取り、SpeakerPicker / LocationPicker にさらに drill
- 提案: `ScriptEditContext` を `ScriptEditPanel.tsx` で provide し、`useScriptEdit()` で各子コンポーネントが必要なだけ pick

- [ ] `ScriptEditContext.tsx` (新規) を作成
- [ ] `CaptionEditor.tsx` 抽出
- [ ] `SceneGridView.tsx` 抽出
- [ ] `SpeakerMappingSection.tsx` 抽出
- [ ] 既存 `SceneEditor.tsx` を Context 経由に書き換え

#### 3.1.4 `config.py` 867 行 → 関心分離

**現状:** ElevenLabs / TTS / Emotion / Kling / Lipsync / Cache / Cost / QA が 1 ファイル

**分割案:**

```
config/
  __init__.py     ← 後方互換の re-export (= 全 const を import して export)
  api_keys.py     ← 各 API key の env 読み込み
  tts.py          ← ElevenLabs / TTS / Emotion 設定
  visual.py       ← Imagen / Kling 設定
  audio.py        ← Lipsync / SYNCSO 設定
  cache.py        ← BG / Kling / Clip cache 設定
  cost.py         ← Cost tracker 設定
  qa.py           ← QA validator 設定
```

- [ ] `config/` パッケージ化 (= 既存 `config.py` を `config/__init__.py` にして 中身を分散)
- [ ] 後方互換のため `from config import X` は全部動くこと (= **init**.py で re-export)
- [ ] 段階的に caller を `from config.tts import X` 経由に移行 (= 急がず、隣接修正で寄せる)

### 3.2 外部 API クライアント共通基盤

**現状の不統一:**

| Client            | retry 回数 | backoff schedule  | timeout 設定           | exception class       | client pool  |
| ----------------- | ---------- | ----------------- | ---------------------- | --------------------- | ------------ |
| elevenlabs_client | 5          | [10,20,40,80,120] | 120s (param)           | ElevenLabsClientError | global       |
| imagen_client     | 2          | (5, 15)           | 120s (REQUEST_TIMEOUT) | RuntimeError          | global       |
| fal_video_client  | 5          | [10,20,40,80,120] | 300s (hardcode)        | FalClientError        | global       |
| lipsync_client    | (内蔵)     | (内蔵)            | 30s (hardcode 散在)    | LipsyncClientError    | global       |
| video_analyzer    | (なし)     | (なし)            | (SDK default)          | RuntimeError          | **毎回新規** |
| gemini_rewriter   | 2          | (5, 15)           | (SDK default)          | (broad except)        | **毎回新規** |

**修正案:**

```python
# common/api_client.py (新規)
class APIClientError(RuntimeError):
    """全 API client 例外の親クラス。"""
    def __init__(self, message: str, *, status: int | None = None,
                 retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable

def call_with_retry(fn: Callable, *, max_retries: int, backoff: list[float],
                    classify: Callable[[Exception], bool] | None = None,
                    logger: logging.Logger) -> T:
    """共通リトライ + backoff + log。classify は retry 判定。"""
    ...
```

- [ ] `common/api_client.py` 新規追加 (= APIClientError + call_with_retry)
- [ ] 各 client の retry ループを `call_with_retry` 経由に書き換え (= 1 PR / 1 client、段階移行)
- [ ] `ElevenLabsClientError` / `FalClientError` / `LipsyncClientError` を `APIClientError` 継承に
- [ ] `imagen_client` / `video_analyzer` / `gemini_rewriter` の `RuntimeError` を `APIClientError` 派生に置換
- [ ] `video_analyzer.py:219` / `gemini_dialogue_rewriter.py:216` の毎回新規 client 作成を module-level singleton に
- [ ] timeout を `config.api_timeouts.{provider}_request_sec` 形式で一元化

### 3.3 巨大関数の責務分離

| 場所                                                    | 行数 | 責務                                                               | 改善案                             |
| ------------------------------------------------------- | ---- | ------------------------------------------------------------------ | ---------------------------------- |
| `analyze/pipeline.py:283-613` `run()`                   | 330  | frames / audio / whisper / acoustic / claude / save / rewrite      | フェーズごとに private 関数に分解  |
| `final_import/publish.py:75-277` `publish()`            | 200+ | YouTube / IG / TikTok の dispatch + analytics                      | 各 platform 別 dispatch 関数を分離 |
| `analytics/db.py:48-146` `init_db()`                    | 100  | version check / schema apply / column migration                    | 3 関数に分割                       |
| `staged_pipeline.py:604-777` `apply_scene_boundaries()` | 176  | flat化 / regroup / subtitle reset / file cleanup / progress reset  | 5 関数に分解                       |
| `compositor.py:460-584` `_build_overlay_filter()`       | 127  | scenes/lines/chunks の 3 重 nested loop で filter_complex 組み立て | chunk 生成を独立関数に             |

- [ ] `analyze/pipeline.py` の `run()` をフェーズ別に分解 (= `_phase_extract_frames` / `_phase_transcribe` / `_phase_claude_inference` 等)
- [ ] `final_import/publish.py` を platform dispatch table 化 (= `_PUBLISHERS: dict[str, Callable]`)
- [ ] `analytics/db.py` の `init_db()` を `_apply_schema` / `_run_migrations` / `_ensure_indices` に分割
- [ ] `staged_pipeline.py` の `apply_scene_boundaries()` を 5 関数 (`_flatten_lines` / `_regroup_by_boundary` / `_reset_subtitle_timings` / `_cleanup_stale_artifacts` / `_reset_progress_after_boundary`) に
- [ ] `compositor.py` の `_build_overlay_filter()` の chunk 解決を独立関数に

### 3.4 設計違反

- [ ] **`staged_pipeline.py:754`** が `scene_gen._build_audios_from_full()` という private 関数を直接呼び出している → 2.4 と合わせて public wrapper 経由に
- [ ] **`final_import/publish.py:316-367`** `_ensure_video_in_analytics()` が `project_state.read_metadata()` と `staged_pipeline.load_project_screenplay()` を直接読み込み → publish は `final_import/core.py` の API を経由すべき (= レイヤ違反)
- [ ] **`scripts/` 28 ファイル / 13 ファイルが `log_setup.setup()` を独立呼び出し** → `scripts/_cli_base.py` (新規) に共通の ArgumentParser ベース + logger 初期化を集約

### 3.5 frontend Error Boundary 欠如

**現状:** 1 子コンポーネントの crash が全体を白画面化する

- [ ] `frontend/src/components/ErrorBoundary.tsx` 新規作成
- [ ] `App.tsx` の各 page route / 各 Stage\* コンポーネント を ErrorBoundary で包む
- [ ] エラー時の fallback UI (= 「リロード」「issue 報告」ボタン) を統一

### 3.6 OAuth refresh token 管理

**現状:** `platform_clients/youtube.py:207-254` `_oauth_access_token()` が refresh token を expire 検知しない (= Google の access_token は 1h 寿命だが、refresh 自体が失敗する経路がない)

- [ ] `_oauth_access_token()` で 401 を検知したら refresh 流して再試行
- [ ] refresh token 自体が revoke された場合の error message を整備 (= 「再認可してください」+ 手順への link)

### 3.7 重複コードと duplication

- [ ] `routes/projects.py:152-171` の jsonify エラーパターンを `api_error()` 統一
- [ ] `platform_clients/youtube.py` の `_resolve_oauth_env()` → `_oauth_access_token()` → API 呼び出し pattern が 3 度繰り返し (upload / fetch_analytics / fetch_public_stats) → 専用 `YouTubeAPIClient` クラスに統合

### 3.8 testing 基盤

- [ ] **`tests/factories/` が 0 件 use** → 既存テストはそのまま、**新規テストから factories 経由を必須化** (= PR テンプレートに checklist 追加)
- [ ] `tests/conftest.py:58-70` `_stub_character_images` の autouse 副作用を Docstring で明示し、`@pytest.mark.real_characters_dir` の使い方を `docs/developments/testing.md` §5 に追記
- [ ] `tests/test_build_audios_parity.py` 新規追加 (= 2.4 と合わせて)

### 3.9 publish 後の analytics DB 登録失敗の検知 + 復旧 (= 設計の弱点補強)

**背景:**

`final_import/publish.py:_record_analytics()` は SNS upload 成功後の analytics DB 登録失敗を **graceful に許容** する (= `metadata.json.published_posts[].analytics_persisted=false` + `analytics_warning` を残して publish 自体は成功扱い)。これは CLAUDE.md と publish.py:282-291 の docstring に明記された **意図された設計** で、Critical ではない。

しかし実物検証 (2026-05-17) で 3 つの実用的な弱点が判明した:

**弱点 1: 手動復旧 script が FK 違反で詰む可能性**

- `analytics/schema.sql:60` で `posts.video_id` に `REFERENCES videos(id) NOT NULL` 制約あり
- `publish.py:_record_analytics()` は `_ensure_video_in_analytics()` → `register_post()` の順で呼ぶ
- `scripts/register_post.py` は **`_ensure_video_in_analytics()` を呼ばない**
- → `_ensure_video_in_analytics()` 段階で失敗していた場合 (= videos / screenplays への INSERT が一緒に落ちる)、運用者が `register_post.py` を実行しても FK 違反で fail する
- 真の復旧手順は `ingest_screenplay.py` → `ingest_video.py` → `register_post.py` の 3 段だが、error log には 1 段しか書かれていない

**弱点 2: 検知メカニズムが完全に受動的**

- `analytics_persisted=false` を能動的に scan する仕組みが **どこにも無い** (= grep 結果: 参照は test + publish.py 内のみ)
- dashboard widget 無し / cron scan 無し / Slack 通知 無し / 自動 retry 無し
- → 運用者が error log を見落とすと、永久に metrics 取得対象から漏れる (= `fetch_metrics.py` は `v_active_posts` を見るので未登録 post は永久に蓄積されない)

**弱点 3: 「極めてまれ」の前提が狭い**

- CLAUDE.md は「disk full / SQLite 内部エラー」と書くが、実用的な障害モードは: WAL ファイル破損 / 同時実行ロック競合 (= auto_loop と手動 publish の並走) / schema migration 失敗 / permission 問題 など複数
- `register_post()` は `INSERT OR REPLACE` で idempotent なので、瞬間障害なら数秒後の自動 retry で吸収できる。今の手動運用は保守的すぎる

**最小コストな改善案:**

outbox pattern のような大改修は不要。以下 3 点で十分:

- [ ] **`scripts/reconcile_publish.py` 新規** — `temp/*/metadata.json.published_posts[]` を全 project scan し、`analytics_persisted=false` を見つけたら `_ensure_video_in_analytics()` + `register_post()` を自動 retry。idempotent なので安全。cron で 1 日 1 回 (= 既存 ops/launchd に追加)。成功時は metadata の `analytics_persisted` を `true` に更新し `analytics_warning` を消す
- [ ] **`scripts/register_post.py` を `_ensure_video_in_analytics()` 経由に書き換え** — 3 段がけ手順を 1 コマンドに集約。error log の復旧コマンド指示も 1 行に統一
- [ ] **dashboard に「未同期 publish」widget 追加** — `scripts/dashboard.py` に `analytics_persisted=false` の published_posts を一覧表示。運用者が一目で気付ける

**Why High (= Critical ではない理由):**

- データ消失ではなく **登録漏れ** (= 動画自体は SNS に存在し、視聴可能)
- 既に `metadata.json` に痕跡が残るので、後追い復旧は可能
- ただし 上記 3 点の改善なしには「設計通りに動いているが、誰も気付かない」状態が成立するため、運用上 High 優先度

### 3.10 設計ドキュメント鮮度の自動監視 (= drift 解消 + 新規 SSOT は作らない)

**背景:**

実証 (2026-05-17) で 3 つの設計 doc に drift が確認された:

- `docs/developments/ubiquitous-language.md` (= 最終更新 2026-05-07、10 日遅れ) — L19 に `speaker_to_ref` (= #209 で撤廃済) が残存。per-character TTS (#202) / Gemini rewrite (#204) / `recommended_wardrobes` (#197) の新用語が未登録
- `docs/developments/architecture.md` (= 最終更新 2026-05-09、8 日遅れ) — Stage 2 TTS dispatcher 化 (#202) / Gemini rewrite phase (#204) / Remotion 撤去 (#199) が未反映
- `docs/abstract-screenplay-design.md` — 今日 (2026-05-17) 更新済みなのに L42-220 で旧 `speaker_to_ref` 説明が残存。L14 で「以下は歴史的記録」と注釈付けて逃げている (= 半端更新)

**判断: 新規 SSOT doc は作らない**

「設計全体像を 1 ファイルにまとめる」案は **症状への対処** にしかならない。真の問題は doc 数ではなく **コミット時に doc を更新するワークフローが定着していない** こと。新規 doc を作っても更新サボりは引き継がれる。さらに:

- 既に `CLAUDE.md` (420 行、今日更新済み) が事実上の SSOT として台本スキーマ + Stage 仕様 + 操作フロー + dispatcher 構造を網羅
- `docs/developments/overview.md` (今日更新済み) が目的別 routing を担う
- 統合 doc を新設すると CLAUDE.md と 80% 重複し、2000 行超の monolith になり誰も全部読まなくなる
- 既存の責務分離 (`ubiquitous-language.md` = 用語辞書 / `architecture.md` = レイヤ / `testing.md` = テスト戦略) は目的別索引として正しい設計

**改善方針: 既存 doc の鮮度を機械的に保証**

- [ ] **PR テンプレート checklist 整備** (= `.github/pull_request_template.md` 新規) — 「該当する設計 doc を更新したか?」を checkbox 化: - `[ ] architecture.md` (= レイヤ / 依存方向 / Stage × 外部 API マトリクスに変更があるか) - `[ ] ubiquitous-language.md` (= 新用語追加 / 既存用語の撤廃があるか) - `[ ] CLAUDE.md` (= Stage 仕様 / 操作フロー / 主要スキーマに変更があるか)
- [ ] **claude-code PostToolUse hook 追加** (= プロジェクト `.claude/settings.json`) — 主要モジュール (`scene_gen.py` / `analyze/*.py` / `staged_pipeline.py` / `config.py` / `screenplay_validator.py`) を Edit / Write したら、対応する doc 更新を提案する hook を仕込む (= `update-config` skill 経由)
- [ ] **CI で stale 警告** (= 将来 CI 構築時) — `architecture.md` / `ubiquitous-language.md` の最終更新日が直近 30 日のコミット内の主要モジュール変更日より 14 日以上古ければ warn
- [ ] **「歴史的記録」注釈の禁止** を `docs/developments/coding-rules.md` §6 (コメント / docstring) に追記 — 旧情報は git history に任せて削除する原則。`abstract-screenplay-design.md` L14 のような「以下は歴史的記録」型の半端更新を撲滅
- [ ] **既存 drift の即時解消** (= 3 PR、各 1 doc): - `ubiquitous-language.md` から `speaker_to_ref` 行 (L19) を削除、per-character TTS / Gemini rewrite / `recommended_wardrobes` を追加 - `architecture.md` を最新コミットまで追従 (= Stage 2 dispatcher 経路 / analyze pipeline の rewrite phase / Remotion 撤去を反映) - `abstract-screenplay-design.md` の L42-220 旧 schema 記述を全削除し、現行 (= `line.speaker` 直書き方式) に統一

**Why High (≠ Critical):**

- 設計 drift は実害が **遅延して** 現れる (= 新規開発者が誤情報を信じてコード書く / Claude Code が古い doc を読んで誤推論する → リファクタリング計画書のような誤判断につながる)
- 「実装は変わったが doc は古い」状態は **嘘の SSOT** で、ドキュメントが無い状態より有害
- ただしユーザー機能に直接の影響は無いため Critical ではない

---

## 4. Medium (= 余裕があれば寄せる)

### 4.1 マジックナンバー

- [ ] `scene_gen.py:1378,1578` の `0.05` を `MIN_SPEECH_DURATION_SEC` 定数化
- [ ] `scene_gen.py:1695-1709` の `target=2.0` 上限を `GLOBAL_SPEED_CEILING` config 化
- [ ] `scene_gen.py:627,637` の `anullsrc=r=44100:cl=stereo` を config parameter 化
- [ ] `platform_clients/youtube.py:28` `UPLOAD_STATE_TTL_SEC = 24 * 3600` は良い例。同レベルで `fal_video_client.py:96` の `300s` を config 化

### 4.2 ログ規約違反

- [ ] `frontend/src/components/stages/StageBG.tsx:179` / `StageKling.tsx:214` の `console.error(e)` を統一 logger に
- [ ] (Python 側は CLAUDE.md §coding-rules で既に f-string 禁止だが、`logger.exception` の使用率が低い → 隣接修正で寄せる)
- [ ] `scripts/` 配下 172 件の `print()` → `logger.info` に置換 (= `_cli_base.py` 抽出と同時)

### 4.3 廃止コード残骸

- [ ] `scripts/migrate_screenplay_v2.py` / `v3.py` / `migrate_to_project_snapshot.py` / `migrate_intent_suggestions.py` / `migrate_speaker_schema.py` / `migrate_speaker_to_ref.py` / `migrate_characters_layout.py` の 7 スクリプトを `scripts/_archive/` に移動 (= 一度実行済みで再実行されない一時 script)
- [ ] `routes/_helpers.py` の `api_error()` への移行を完了した時点で、`preview_server.py` 内の error response helper の重複を削除

### 4.4 スキーマ不一致

- [ ] `locations/soft_gradient.json` に `recommended_wardrobes` フィールド追加 (= 他 4 ロケには存在、一貫性のため)
- [ ] `analytics/db.py` の schema migration テスト (= version 1 → 最新の migrate が壊れていないことの test) を `tests/test_analytics_db_migration.py` に追加

### 4.5 tempfile / 防御性

- [ ] `audio_features.py:20-23` の `tempfile(delete=False)` + 手動 `os.remove` を `tempfile.NamedTemporaryFile` の context manager に
- [ ] `bg_cache.py:181` の cleanup error swallow に `logger.warning` 追加

### 4.6 cost_tracking 一貫性

- [ ] `video_analyzer.py:150-156` の `ScreenplayParseError` への usage 同梱 convention vs `gemini_dialogue_rewriter.py:367` の string repr 同梱 vs `elevenlabs_client` の pricebook 動的 fetch を統一
- [ ] 各 client が `cost_tracking.recorder` を呼ぶタイミングを cheat sheet 化 (= `docs/developments/cost-tracking-convention.md` 新規)

---

## 5. Low (= nice to have)

- [ ] `frontend/src/components/stages/StageTTS.tsx:50-127` の `lineCost` / `_sumCost` を `tts-cost.ts` に抽出
- [ ] `compositor.py:135-180` の `_BREAK_STRONG` / `_BREAK_PARTICLES_1CHAR` 等の rule set に「何用か」のコメント追加
- [ ] `scripts/` 全 CLI に `--help` の docstring を統一テンプレートで整備
- [ ] `frontend` の `key={index}` 使用箇所を unique id base に置換
- [ ] `analytics/db.py` の SQL を `query_*.sql` ファイルに切り出して syntax highlight 対応 (= 任意)
- [ ] `kling_cache.py:215-284` `_evaluate_fitness` の加重 formula 透明化 (= docs/developments/clip-library に formula 表)

---

## 6. Phase 別実施計画

依存関係を考慮した実施順。**1 PR = 1 項目** を基本に。

### Phase 0: Critical 即時対応 (= 1-2 PR / 着手から 1 週間)

- 2.1 lipsync_client の JSON 防御性 (= 1 PR、~50 行 diff)
- 2.2 API response log 漏洩 (= 1 PR、~30 行 diff)
- 2.3 analytics/db.py f-string SQL の whitelist 強化 (= 1 PR、~40 行 diff)

### Phase 1: 共通基盤抽出 (= 3-5 PR / 2 週間)

- 3.2 外部 API client 共通基盤 (`common/api_client.py`)
- 3.5 frontend Error Boundary
- 3.4 `scripts/_cli_base.py` 抽出 + scripts/ の print() → logger 移行 (= まとめて)
- 3.8 testing 基盤強化 (= factories 必須化、parity テスト)
- 3.10-a 既存 doc drift の即時解消 (3 PR: ubiquitous-language / architecture / abstract-screenplay)
- 3.10-b PR テンプレート checklist + claude-code PostToolUse hook 整備

### Phase 2: 大型モジュール分割 (= 5-8 PR / 4-6 週間)

- **2.4 を最初に** (Critical だが scene_gen 分割と密接) → `_extract_line_audio_segment()` 抽出 + parity test
- 3.1.1 `scene_gen.py` → `stages/` 分割 (4 PR: bg → kling → audio → scene)
- 3.1.2 `preview_server.py` → routes/ 完全移行 (2 PR: 残 endpoint 移動 → jsonify 統一)
- 3.1.3 `ScriptEditPanel.tsx` → 4 ファイル分割 (3 PR: Context → SceneGridView → SpeakerMappingSection)
- 3.1.4 `config.py` → `config/` パッケージ化 (1 PR)
- 3.3 巨大関数の責務分離 (= 各箇所 1 PR、計 5 PR)

### Phase 3: 設計違反 + 残骸クリーンアップ (= 2-3 PR / 1 週間)

- 3.4 staged_pipeline / final_import のレイヤ違反修正
- 3.6 OAuth refresh token 管理
- 3.9 publish-analytics 不整合の検知 + 復旧 (= `reconcile_publish.py` + `register_post.py` 改修 + dashboard widget)
- 4.3 廃止 migration scripts を `scripts/_archive/` へ
- 4.4 locations スキーマ統一 + migration テスト追加

### Phase 4: 継続的改善 (= 機会があるたびに寄せる)

- 4.1 マジックナンバー / 4.2 ログ規約 / 4.5 tempfile / 4.6 cost_tracking 一貫性
- 5.x Low 全般

---

## 7. 計測指標

リファクタの効果を客観的に把握するため、定期的に以下を測る:

| 指標                                                     | 現在値 (2026-05-17)                     | 目標 (Phase 3 完了時)                  |
| -------------------------------------------------------- | --------------------------------------- | -------------------------------------- |
| `scene_gen.py` 行数                                      | 2671                                    | < 500                                  |
| `preview_server.py` 行数                                 | 1544                                    | < 200                                  |
| `ScriptEditPanel.tsx` 行数                               | 1651                                    | < 400                                  |
| `config.py` 行数                                         | 867                                     | (パッケージ化のため計測対象外)         |
| `scripts/` の `print()` 件数                             | 172                                     | < 10 (= 真に CLI 出力のみ)             |
| `tests/factories/` の `from factories` import            | 0                                       | 新規テストの 100%                      |
| `preview_server.py` の `jsonify({"error"...})`           | 74                                      | 0 (全て `api_error()` 経由)            |
| 外部 API client の `RuntimeError` 直接 raise             | 4 (imagen / video_analyzer 等)          | 0 (全て APIClientError 派生)           |
| `analytics_persisted=false` を能動的に scan する仕組み   | 0 (検知メカニズム無し)                  | 1 (= `reconcile_publish.py` cron 稼働) |
| 設計 doc の drift (= 主要モジュール変更日 vs doc 更新日) | 3 doc が 8-10 日 stale + 1 doc 内部矛盾 | 0 (= 全 doc が直近 14 日以内に追従)    |

---

## 8. 注意事項

### 8.1 やらないこと

- 「動画 / 背景 / TTS / lipsync を再生成して確認する」(= CLAUDE.md コスト規律違反)
- 「既存テスト 80+ ファイルを一斉に factories 経由に書き換える」(= testing.md §10 違反)
- 「リファクタついでに機能追加」(= coding-rules.md §1 違反)
- 「後方互換のためのリエクスポートを永続的に残す」(= Phase 2 完了時には消す)

### 8.2 例外的に許容すること

- `stages/` 分割中の `scene_gen.py` の re-export は **移行期間中だけ** 許容 (= 各分割 PR の最終で全削除)
- `config/` パッケージ化後の `config/__init__.py` での re-export は **当面恒久的** に維持 (= caller 全部の `from config import X` を書き換える PR は別途出す)

### 8.3 計画の更新

- 本計画は **着手前のスナップショット**。実施過程で見つかった追加負債は本ファイル末尾に「追補」セクションで追記
- 各 Phase 完了時に該当 checkbox を `[x]` 化し、PR # を付記する
- Phase 4 は完了概念がないため、四半期ごとに `analyze-refactoring` skill で再走査する

---

## 9. 関連ドキュメント

- `docs/developments/architecture.md` — レイヤ・依存方向 (= 3.4 の判定基準)
- `docs/developments/coding-rules.md` — 命名 / ログ / エラー / コメント規約
- `docs/developments/testing.md` — factories / fixture / カバレッジ目標
- `docs/developments/ubiquitous-language.md` — ドメイン用語の SSOT
- `CLAUDE.md` — プロジェクトの最重要ルール (汎用性 / コスト規律 / スコープ厳守)
