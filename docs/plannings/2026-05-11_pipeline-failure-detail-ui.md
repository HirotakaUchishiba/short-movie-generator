# Pipeline Failure Detail UI Surface — Design + Implementation Plan

**date**: 2026-05-11 / **status**: draft (= 実装 phase A 着手前) / **branch**: `feat/pipeline-failure-detail-ui`

## 0. 背景

2026-05-11 22:09 JST に project `20260511_220521` の analyze が失敗した時の UI 画面では「⚠️ 分析が失敗しました」「以下から選んでください。retry は cache (= frames / audio / whisper) が効くので追加課金は最小です。」だけが表示され、**原因 (= Anthropic API のクレジット残高不足)** が UI から見えなかった。

実際の error 本体は `tmp-progress.json` に格納されていた:

```
"stages.analyze.error":
  "runner error: Error code: 400 - {'type': 'error',
   'error': {'type': 'invalid_request_error',
   'message': 'Your credit balance is too low to access the Anthropic API.
              Please go to Plans & Billing to upgrade or purchase credits.'},
   'request_id': 'req_011CavqQUqWoWA18DYbfv4RK'}"
```

つまり **バックエンドは情報を持っているのに UI が表示していない**。同様の問題は analyze 以外の全 stage に潜在する (= Stage 2 ElevenLabs / Stage 3 Imagen / Stage 4 fal.ai / Stage 5 Sync.so / Stage 6 ffmpeg/Remotion / Stage 7 import / Stage 8 YouTube・IG・TikTok)。

本 doc では **失敗箇所を全列挙** し、**「UI で何が原因かを把握できる」** ための実装方針を Phase 単位で記す。

---

## 1. TL;DR

| 項目           | 内容                                                                                                                               |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **goal**       | 全 stage の失敗時に UI に **error_type + message + actionable_hint + request_id** を出す                                           |
| **scope**      | Stage 0 (analyze) + Stage 1-6 (生成) + Stage 7 (import) + Stage 8 (publish)                                                        |
| **非 scope**   | CLI / cron 経路の失敗 (= UI を経由しない) は別途。analytics 補助 script (= `scripts/fetch_*.py` 等) は今回触らない                 |
| **Phase 数**   | 4 (= Backend SSOT / 各 stage wire / Frontend types & component / 全 page 適用)                                                     |
| **不変条件**   | (1) 既存 success path は無変更、(2) 課金 retry の説明は維持、(3) error capture は best-effort で、保存失敗時も pipeline は止めない |
| **見積コスト** | 設計 0.5 日 + 実装 1.5 日 + テスト 0.5 日                                                                                          |

---

## 2. 現状調査 (= 失敗箇所マップ)

### 2.1 Stage 0 (analyze pipeline)

| phase      | 失敗原因例                                                                          | 現状の捕捉                                                                                                                                        | 保存先                                                                                                   | UI 露出                                                    |
| ---------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| frames     | ffmpeg 不存在 / 動画破損                                                            | `analyze/pipeline.py:105` RuntimeError                                                                                                            | `analyze_phases.error` (← runner 経由)                                                                   | ❌                                                         |
| audio      | ffmpeg 不存在 / 抽出失敗                                                            | `pipeline.py:122` RuntimeError                                                                                                                    | `analyze_phases.error`                                                                                   | ❌                                                         |
| whisper    | OpenAI API クレジット切れ / 429 / モデル DL 失敗                                    | **uncaught** → `runner._run_job` の generic catch                                                                                                 | `analyze_jobs.error` (= str(e))                                                                          | ❌                                                         |
| acoustic   | librosa 失敗 / audio 読込失敗                                                       | **uncaught** → 同上                                                                                                                               | `analyze_jobs.error`                                                                                     | ❌                                                         |
| **claude** | Anthropic API クレジット切れ / context 超過 / 401 / 429 / timeout / JSON parse 失敗 | `video_analyzer.py:309-315` で `ScreenplayParseError` raise → `pipeline.py:469` で再 raise → `runner.py:299-302` で `analyze_jobs.error` のみ更新 | `analyze_jobs.error` + `tmp-progress.json.stages.analyze.error` (= `mark_analyze_failed` で `:500` 截断) | ⚠️ AnalyzeJobView だけ表示、AnalyzeStage0Page は表示しない |
| save       | metadata 追記失敗                                                                   | `pipeline.py:538` warning log のみ                                                                                                                | 保存されない                                                                                             | ❌                                                         |

**致命的な穴**: claude phase 失敗時に `analyze_phases.error` (= phase 単位の seam) には書かれず、`analyze_jobs.error` (= job 全体の seam) にだけ str(e) で入る。UI 側は SSE event `failed` の `error` field を AnalyzeJobView は表示しているが、**AnalyzeStage0Page (= ユーザがスクリーンショットを撮ったページ)** は受け取っていない。

### 2.2 Stage 1-6 (生成パイプライン本体)

| stage     | 外部依存                | 失敗原因例                                          | 現状の捕捉                                                                                                       | 保存先                                  | UI 露出 |
| --------- | ----------------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | --------------------------------------- | ------- |
| 1.script  | (なし、純粋 validation) | screenplay schema 違反                              | `staged_pipeline.run_script` で raise → `run_next_stage:589-592` catch                                           | `_record_stage_run` → analytics.db のみ | ❌      |
| 2.tts     | ElevenLabs API          | 認証 / クレジット切れ / 429 / unsupported voice     | `tts/elevenlabs_client.py:_classify_status()` → ClientError raise → `staged_pipeline.run_next_stage:589` catch   | analytics.db のみ                       | ❌      |
| 3.bg      | Google Imagen API       | quota / 429 / safety filter                         | `scene_gen.py` ThreadPool catch → `PartialBackgroundFailure` raise → run_next_stage:589 catch                    | analytics.db のみ                       | ❌      |
| 4.kling   | fal.ai Kling            | クレジット切れ / job timeout / 429 / video too long | `fal_video_client._classify_error()` → ClientError raise → `PartialKlingFailure` 集約 → run_next_stage:589 catch | analytics.db のみ                       | ❌      |
| 5.scene   | Sync.so lipsync         | 認証 / クレジット切れ / file >20MB / 不正音声       | `lipsync_client.py:56-98` で例外 raise → run_next_stage:589 catch                                                | analytics.db のみ                       | ❌      |
| 6.overlay | ffmpeg / Remotion CLI   | binary 不存在 / 構文 / disk full                    | `compositor.py:104-107` RuntimeError raise → run_next_stage:589 catch                                            | analytics.db のみ                       | ❌      |

**共通の穴**: `staged_pipeline.run_next_stage` の `except Exception as e:` (= L589) は **`_record_stage_run(...status="failed", error=str(e))` で analytics.db に書くだけ** で、`progress_store` には書かない。`tmp-progress.json.stages.<stage>.error` field は存在しない (= UI が読みに行く SSOT)。

### 2.3 Stage 7 (final_import) + Stage 8 (publish)

| 経路                                | 失敗原因                                                 | 捕捉                                                | 保存先                                         | UI 露出                        |
| ----------------------------------- | -------------------------------------------------------- | --------------------------------------------------- | ---------------------------------------------- | ------------------------------ |
| Stage 7 import                      | mp4 ftyp atom 不正 / 元 file 不存在 / disk full          | `final_import/core.py:136-139` RuntimeError         | 例外発火のみ                                   | ❌                             |
| Stage 8 YouTube init                | OAuth token 失効 (401) / quota (403) / network           | `platform_clients/youtube.py:643-656` raise         | exception 伝播                                 | ❌                             |
| Stage 8 YouTube chunk upload        | network / chunk timeout / 308 unknown offset             | `youtube.py:699-764` RuntimeError                   | exception 伝播                                 | ❌                             |
| Stage 8 YouTube final commit        | video_id 未取得 / JSON parse 失敗                        | `youtube.py:770-774` RuntimeError                   | exception 伝播                                 | ❌                             |
| Stage 8 Instagram API               | アクセストークン失効 / Graph API 403 / container timeout | `platform_clients/instagram.py:108-150` raise       | exception 伝播                                 | ❌                             |
| Stage 8 TikTok                      | token 失効 / Display API 未対応                          | `platform_clients/tiktok.py:26-29` RuntimeError     | exception 伝播                                 | ❌                             |
| Stage 8 半自動 (clipboard/app 起動) | pbcopy / open -a 失敗                                    | `publish.py:155-170`                                | `metadata.published_posts[].failure_reason`    | ⚠️ metadata だが UI 側で表示無 |
| Stage 8 analytics DB 登録失敗       | SQLite disk full / lock                                  | `publish.py:251-285` `_record_analytics()` で catch | `metadata.published_posts[].analytics_warning` | ⚠️ metadata だが UI 側で表示無 |

**穴**: Stage 7 / 8 は `EXTERNAL_ACTION_STAGES` で `progress_store.mark_failed` 経路が定義されていない (= そもそも `mark_failed` という関数自体が `mark_analyze_failed` の analyze 専用しかない)。

### 2.4 Frontend

| component / page                        | 対象 stage  | 現状の失敗表示                               | error 本文表示?                          |
| --------------------------------------- | ----------- | -------------------------------------------- | ---------------------------------------- |
| `AnalyzeStage0Page.tsx`                 | analyze (0) | "分析が失敗しました" + retry/delete ボタン   | ❌                                       |
| `AnalyzeJobView.tsx`                    | analyze (0) | `{job.error}` を text-rose で表示            | ✅ (= raw 文字列のみ、phase 不明)        |
| `ProjectCard.tsx`                       | (一覧)      | "⚠ 分析失敗" バッジ                          | ❌ tooltip 無                            |
| `StageScript.tsx` 〜 `StageOverlay.tsx` | 1-6         | local error state のみ (= UI 操作失敗時のみ) | ❌ stage progress の error は読まない    |
| `StageFinalImport.tsx`                  | 7           | local error のみ                             | ❌                                       |
| `StagePublish.tsx`                      | 8           | API 経路の error を string 化                | ⚠️ catch 時のみ、metadata 由来は読まない |

**型レベル**:

- `types.ts:60-64` の `StageStatus` interface に **error field 自体が無い** (= `generated_at` / `approved_at` / `regen_count` の 3 field のみ)。
- `Progress` (`types.ts:66-68`) も error を持たない。
- analyze は `JobStatus` (`types.ts:227`) と `AnalyzeJob` / `AnalyzePhaseRecord` (`types.ts:273, 282`) に error field を持つ (= 既存実装)。

**共通コンポーネント**: `<ErrorPanel>` 系は存在しない。各 component で `{error && <div className="text-rose-400 text-xs">...</div>}` の inline UI が散らばっている。

---

## 3. 設計方針

### 3.1 不変条件 (= 既存挙動を壊さない)

1. **既存 success path は無変更**。新規 field は全 optional。
2. **analyze の `mark_analyze_failed` は維持** (= AnalyzeJobView の SSE event 経路はそのまま動く)。
3. **error capture は best-effort**。`progress_store.mark_stage_failed` の書き込みで例外が出ても、上位の `run_next_stage` の `raise` (= 既存 caller への伝播) は止めない。
4. **保存される error は :2000 字で截断** (= 機微情報のうっかり混入と巨大 stack trace を抑制。analyze の :500 より大きく取り、API error JSON を丸ごと載せられる)。
5. **構造化 error は dict** (= `{type, message, request_id, actionable_hint, retry_cost_estimate, occurred_at}`)、 raw 文字列 path も残す (= 後方互換)。

### 3.2 SSOT の選定

**`tmp-progress.json.stages.<stage>.error_detail`** を SSOT とする (= UI が読みに行く JSON、frontend type が直接 mirror)。

理由:

- すでに analyze は `stages.analyze.error` を使っており、自然な拡張。
- frontend は `getProject` / `getProgress` 経由でこの JSON を取得済 (= 追加 API 不要)。
- analytics.db (= `_record_stage_run`) はバックエンド分析用で、frontend からは読めない (= 単独の error 源としては不十分)。

**新 schema** (= `tmp-progress.json` の各 stage block):

```jsonc
"stages": {
  "tts": {
    "generated_at": null,
    "approved_at": null,
    "regen_count": 0,
    "status": "failed",                       // ← 新 (analyze の既存 status と統一)
    "error_detail": {                         // ← 新 (= 構造化 envelope)
      "type": "credit_exhausted",             //   classifier の出力 (= 既知 8 種)
      "message": "Your credit balance ...",   //   raw error message (:2000)
      "request_id": "req_011Cavq...",         //   nullable
      "actionable_hint": "Anthropic の Plans & Billing でクレジット購入後、リトライしてください",
      "retry_cost_estimate_usd": 3.30,        //   pricebook 履歴 median (nullable)
      "occurred_at": "2026-05-11T22:09:22"
    }
  }
}
```

`error_detail` が無い場合は **失敗していない** か **legacy path** (= 旧 progress.json)。

### 3.3 error_type 分類

`errors/classify.py` (新規) に以下の 8 種 + unknown を定義:

| type               | 検出条件                                                            | actionable_hint (= UI に出す)                                         |
| ------------------ | ------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `credit_exhausted` | message に "credit balance" / "out of credit" / "exhausted balance" | "{provider} のダッシュボードでクレジット購入後、リトライしてください" |
| `rate_limit`       | HTTP 429 or "rate limit"                                            | "数分待ってリトライしてください"                                      |
| `auth_failure`     | HTTP 401 / 403 or "invalid api key" / "unauthenticated"             | ".env の API key を確認してください"                                  |
| `quota_exceeded`   | "quota" / "daily limit"                                             | "翌日のクォータ復帰を待つか、別アカウントに切替"                      |
| `context_too_long` | "input is too long" / "context window"                              | "動画を短くするか fps を下げてリトライ"                               |
| `safety_filter`    | "safety" / "blocked" / "policy"                                     | "プロンプトを調整して再試行"                                          |
| `network_timeout`  | `APIConnectionError` / `APITimeoutError` / `socket.timeout`         | "ネットワーク接続を確認"                                              |
| `disk_full`        | "no space" / `ENOSPC`                                               | "ディスク空きを確保"                                                  |
| `unknown`          | (default)                                                           | "詳細は error message を参照"                                         |

分類は **文字列 match のみ** (= 例外型 introspection は SDK 依存が広がるので避ける)。SDK 由来の dict (= `{type, error: {type, message}}`) は raw message を一緒に保存するので、UI 側で type 表示も可能。

### 3.4 frontend の構造

```
frontend/src/components/common/
  StageFailureAlert.tsx        # ← 新規共通コンポーネント
  StageFailureAlert.test.tsx
```

props:

```typescript
interface StageFailureAlertProps {
  stage: string; // "analyze" / "tts" / ...
  errorDetail: StageErrorDetail; // 構造化 envelope
  onRetry?: () => void; // retry ボタン (= optional)
  onDelete?: () => void; // 削除ボタン
  retryHint?: string; // "retry は cache が効く" 等
}
```

表示構造:

```
┌──────────────────────────────────────┐
│ ⚠️ {stage} で失敗しました ({type})    │
│ {actionable_hint}                     │
│                                       │
│ 詳細を表示 ▼                          │
│   message: {raw message}              │
│   request_id: {request_id or "—"}     │
│   発生時刻: {occurred_at}             │
│   retry コスト見積: ${cost} (= 履歴 median) │
│                                       │
│ [リトライ] [削除] [後で]              │
└──────────────────────────────────────┘
```

詳細セクションは collapsible (= 既定 collapsed)。`<details><summary>` で実装。

---

## 4. 実装計画 (= Phase 分割)

### Phase A: Backend SSOT (= progress_store + classifier)

- [ ] **A1**: `errors/classify.py` (新規) — `classify_error(exc_or_message: Exception | str) -> dict` を実装。8 種 + unknown を返す
- [ ] **A2**: `errors/__init__.py` (新規) — `classify_error` の re-export
- [ ] **A3**: `progress_store.py` — `mark_stage_failed(ts_path, stage, error_detail: dict)` を追加。`stages.<stage>.error_detail` に書く + `status="failed"` 設定。`mark_analyze_failed` も内部的に新経路を呼ぶように刷新 (= 既存 callsite は signature 変更なし、`error_detail.message` だけが旧 `error` 文字列の中身)
- [ ] **A4**: `tests/test_errors_classify.py` (新規) — 8 種 + unknown のサンプル文字列を assert
- [ ] **A5**: `tests/test_progress_store_mark_stage_failed.py` (新規) — 構造化保存 + analyze 既存挙動の保持を確認

**完了条件**: 上記の test が pass、既存の `tests/test_progress_store.py` も全 pass。

### Phase B: 各 stage 経路を wire

- [ ] **B1**: `staged_pipeline.run_next_stage` の `except Exception as e:` (L589) を改修。`classify_error(e)` → `progress_store.mark_stage_failed(ts_path, nxt, error_detail)` を呼ぶ。`_record_stage_run` (analytics.db) は維持
- [ ] **B2**: `analyze/runner.py` の Claude phase 失敗経路 (L299-302) を改修。`analyze_phases` にも phase 単位で `set_phase_failed("claude", error_detail)` を呼ぶ + `mark_analyze_failed` を構造化版に置換
- [ ] **B3**: `analyze/pipeline.py` の各 phase (frames / audio / whisper / acoustic / save) を try/except で包み、失敗時に `set_phase_failed(phase, error_detail)` を呼んでから raise
- [ ] **B4**: `final_import/publish.py` の publish() の outer try/except を整理。`progress_store.mark_stage_failed("publish", ...)` を呼ぶ + metadata の `failure_reason` / `analytics_warning` を `error_detail` 統一形式に揃える
- [ ] **B5**: `final_import/core.py` の `import_final()` 例外経路にも `progress_store.mark_stage_failed("final_import", ...)` を追加

**完了条件**: 各 stage で失敗を強制的に起こす test (= mock で API 失敗) を書き、`tmp-progress.json.stages.<stage>.error_detail` が想定通りに書かれることを確認。

### Phase C: Frontend types + 共通 component

- [ ] **C1**: `frontend/src/types.ts` を改修。
  - `StageErrorDetail` interface 新規 (= 5.2 のスキーマ)
  - `StageStatus` に `status?: "failed" | null` と `error_detail?: StageErrorDetail | null` を追加 (= 全 optional)
  - 既存 `Progress` 等の型に変更なし (= StageStatus 経由で透過)
- [ ] **C2**: `frontend/src/components/common/StageFailureAlert.tsx` 新規 — 3.4 の props + 表示構造を実装。
- [ ] **C3**: `frontend/src/components/common/StageFailureAlert.test.tsx` — error_type 別の表示、collapsible 動作、retry / delete callback の test。

**完了条件**: vitest で StageFailureAlert の test が pass、tsc が clean。

### Phase D: 全 page に wire

- [ ] **D1**: `AnalyzeStage0Page.tsx` — failed 状態のとき `StageFailureAlert` を表示 (= 既存の retry / delete ボタンは内部に統合)
- [ ] **D2**: `AnalyzeJobView.tsx` — phase 単位の error も拾うように拡張 (= 既存 job.error 文字列表示は維持しつつ、error_detail があれば優先)
- [ ] **D3**: `frontend/src/components/stages/StageScript.tsx` 〜 `StageOverlay.tsx` 各 stage page で `progress.stages.<stage>.error_detail` を読み、あれば `StageFailureAlert` を上部に表示
- [ ] **D4**: `StageFinalImport.tsx` / `StagePublish.tsx` も同上
- [ ] **D5**: `ProjectCard.tsx` の「⚠ 失敗」バッジを hover で `error_detail.type + actionable_hint` を tooltip 表示

**完了条件**: 全 page で manually トリガーした failed 状態に対し UI が error message を表示することを vitest で snapshot / integration test。

---

## 5. 影響範囲 (= 触るファイル)

### Backend (新規 2 / 改修 5)

- 新規: `errors/__init__.py`, `errors/classify.py`
- 改修: `progress_store.py`, `staged_pipeline.py`, `analyze/runner.py`, `analyze/pipeline.py`, `final_import/publish.py`, `final_import/core.py`

### Backend tests (新規 5)

- `tests/test_errors_classify.py`
- `tests/test_progress_store_mark_stage_failed.py`
- `tests/test_staged_pipeline_failure_capture.py`
- `tests/test_analyze_pipeline_phase_failure.py`
- `tests/test_publish_failure_capture.py`

### Frontend (新規 2 / 改修 ~10)

- 新規: `frontend/src/components/common/StageFailureAlert.tsx`, `frontend/src/components/common/StageFailureAlert.test.tsx`
- 改修: `frontend/src/types.ts`, 全 stage page (= 上記 D1-D5 リスト)

### Docs

- 本 doc (= `docs/plannings/2026-05-11_pipeline-failure-detail-ui.md`)
- 完了後に `docs/developments/overview.md` §16 に entry 追加

---

## 6. リスク / 不変条件チェック

| リスク                                                 | 緩和策                                                                                         |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| `mark_stage_failed` 内部で例外発生 → pipeline 全体停止 | best-effort で wrap (= `try/except Exception: logger.exception(...)`) して再 raise しない      |
| error_detail が大きすぎて tmp-progress.json が肥大     | message は :2000 截断、stack trace は保存しない                                                |
| analyze 既存挙動の回帰                                 | `mark_analyze_failed` の signature は維持し、内部実装のみ差し替え                              |
| 機微情報 (= API key / 個人情報) の error message 混入  | classifier の actionable_hint は固定文言、message は :2000 で截断 (= ログ regex マスクは別 PR) |
| 旧 progress.json 読込 (= error_detail 不在)            | frontend type で全 optional、表示は `error_detail ? <Alert/> : null`                           |

不変条件 verify:

- ✅ 既存 success path 無変更
- ✅ AI 課金 retry の説明 (= "cache が効く") は維持 (= D1 で `StageFailureAlert.retryHint` に流し込む)
- ✅ EXTERNAL_ACTION_STAGES の `run-next` auto-skip は維持

---

## 7. テスト戦略

### Backend

1. **classify_error** — 8 種 + unknown それぞれに対し代表的 raw message を入力し、想定 type / actionable_hint を返すか
2. **mark_stage_failed** — `tmp-progress.json` に書かれる structure が schema 通り (status / error_detail / occurred_at)、status 変更で他 stage の status が壊れないか
3. **staged_pipeline failure** — mock で `run_tts` を例外 raise させ、progress_store + analytics.db 両方に書かれるか
4. **analyze pipeline phase failure** — Claude API mock で 400 を返し、`analyze_phases["claude"].error` + `analyze_jobs.error` + `tmp-progress.json` 全てに構造化 error が入るか
5. **publish failure** — YouTube API mock で 401 を返し、`metadata.published_posts[].error_detail` + `progress_store.stages.publish` に書かれるか

### Frontend

1. **StageFailureAlert snapshot** — type / message / actionable_hint 表示
2. **StageFailureAlert collapsible** — 詳細セクションを開く / 閉じる
3. **AnalyzeStage0Page** — `analyze_status === "failed"` かつ `error_detail` があるとき StageFailureAlert を render

---

## 8. 関連

- 元の screenshot 経路: 2026-05-11 22:09 JST に `analyze_20260511_220521_a6f46d` で Anthropic credit_exhausted を踏んだ
- 既存 audit doc: `docs/plannings/2026-05-10_full-pipeline-conformance-audit.md` — Stage / API matrix
- 既存 analyze design: `docs/abstract-screenplay-design.md`
- ubiquitous-language: `docs/developments/ubiquitous-language.md` (= 用語表に "error_detail" を追記する候補)
