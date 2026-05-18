# Cost Tracking 規約

外部 API 課金が発生する各 stage / client で **必ず
`cost_tracking.recorder` を呼び出して `data/cost_records.jsonl` に追記する**
ことを保証するための規約集。`scripts/dashboard.py` の cost 集計 /
`data/pricebook.json` の単価更新 / Phase 1 のフルオート予算 gate
(= `DAILY_COST_CAP_USD`) はすべて本ログを SSOT として読む。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §4.6

---

## 1. recorder 関数の対応表

| stage           | 関数                        | 課金単位                     | provider   | caller (= 期待)                    |
| --------------- | --------------------------- | ---------------------------- | ---------- | ---------------------------------- |
| analyze         | `record_analyze()`          | input_tokens / output_tokens | anthropic  | `analyze/pipeline.py`              |
| analyze_rewrite | `record_dialogue_rewrite()` | input_tokens / output_tokens | google     | `gemini_dialogue_rewriter`         |
| tts             | `record_tts()`              | characters (= text 長)       | elevenlabs | `scene_gen` (= per-line 集約)      |
| bg              | `record_imagen()`           | image_count                  | google     | `scene_gen._generate_background_*` |
| kling           | `record_kling()`            | duration_sec (= 5 / 10)      | fal        | `scene_gen._generate_kling`        |
| lipsync         | `record_lipsync()`          | duration_sec                 | sync       | `scene_gen._apply_lipsync_*`       |

各関数の戻り値は `records.CostRecord` で、caller は metadata だけ流して
記録の詳細 (= 単価計算 / JSONL append) は recorder に任せる設計。

---

## 2. 呼び出し方の規約

### 2.1 必須: 必ず recorder 経由で記録する

API 呼び出しが成功した直後 (= cost 課金が確定した時点) に **同 transaction
内で** recorder を呼ぶ。失敗時 (= retry 後の最終 fail) は記録しない
(= §2.2 例外あり)。

```python
resp = api_client.call(...)
cost_recorder.record_xxx(
    project_ts=ts,
    model=MODEL_ID,
    units...,
    metadata={...},
)
```

### 2.2 失敗時の記録 — scope に応じて分ける

| ケース                | 記録                                                                |
| --------------------- | ------------------------------------------------------------------- |
| API 呼び出し成功      | 必ず記録 (= 課金確定)                                               |
| retry 中の失敗        | 記録しない (= 最終成功 / 最終失敗のみ記録)                          |
| 最終失敗 (= reject)   | API が課金してれば記録、無料エラー (= validation 等) なら記録しない |
| 課金成功 + parse 失敗 | 記録しつつ metadata に `parse_error: true` を残す                   |

### 2.3 metadata 規約 — 推奨フィールド

| キー          | 型   | 意味                                             |
| ------------- | ---- | ------------------------------------------------ |
| `cache_hit`   | bool | cache 経由 skip かどうか (= 課金 0 を区別)       |
| `retry_count` | int  | 最終成功までに何回 retry したか                  |
| `parse_error` | bool | response parse 失敗 (= 課金されたが下流で使えず) |
| `reason`      | str  | parse_error 時のエラー要約 (= 短く)              |

scene_index / line_index は recorder の引数経由で渡す (= metadata より優先)。

---

## 3. 現状の不統一 (= 4.6-a で統一予定)

各 client の **「課金成功 + parse 失敗」エラー時の cost 記録パターン** が
現在ばらついている:

| client                     | 課金成功 + parse 成功  | 課金成功 + parse 失敗                      | 課金失敗 (= API error) |
| -------------------------- | ---------------------- | ------------------------------------------ | ---------------------- |
| `video_analyzer`           | 記録                   | usage を **`ScreenplayParseError` に同梱** | 記録しない             |
| `gemini_dialogue_rewriter` | 記録                   | string repr を **`reason` field に詰める** | 記録しない             |
| `elevenlabs_client`        | 記録 (pricebook fetch) | (parse 失敗ケースは未対応)                 | 記録しない             |
| `imagen_client`            | 記録                   | (parse 失敗ケースは未対応)                 | 記録しない             |

### 統一目標 (= §4.6-a refactor)

すべての client で「**課金成功 + parse 失敗** = `recorder.record_xxx()` に
`metadata={"parse_error": True, "reason": "<short>"}` を渡して記録」 に
統一する。

```python
# 統一後の理想形 (= 全 client 共通)
try:
    parsed = parse_response(resp)
except ParseError as e:
    cost_recorder.record_xxx(
        project_ts=ts, model=MODEL_ID, units...,
        metadata={"parse_error": True, "reason": str(e)[:200]},
    )
    raise APIClientError(f"parse failed: {e}") from e
else:
    cost_recorder.record_xxx(
        project_ts=ts, model=MODEL_ID, units...,
        metadata={"parse_error": False},
    )
    return parsed
```

caller (= 上位 stage) は `metadata.parse_error` 経由でエラーを検知し、
独自の `ScreenplayParseError` への usage 同梱 / 独自 `reason` field 同梱は
廃止する (= cost record 側に一本化)。

---

## 4. dashboard / report での集計

- `scripts/dashboard.py` overview tab で 「累計 cost USD」表示
- `data/cost_records.jsonl` を全部読んで stage / provider 別に group by
- 集計 helper は `cost_tracking/report.py`
- 1 動画あたりの median cost は `cost_tracking/estimator.py` で算出
  (= analyze pipeline の事前見積りで使用)

---

## 5. テスト規約

- 各 stage 関数のテストで `cost_recorder.record_xxx()` の呼び出しを
  `monkeypatch.setattr(cost_recorder, "record_xxx", ...)` で検証する
- 課金 0 (= cache hit) のケースも `cache_hit=True` で記録するか / しないかを
  テストで明示的に固定 (= 仕様の暗黙化を防ぐ)
- `tests/conftest.py:_isolate_cost_records` autouse fixture により本番
  `data/cost_records.jsonl` は自動で隔離されるので、テスト側で
  monkeypatch する必要はない

---

## 6. 関連実装

- `cost_tracking/recorder.py` — `record_*` facade (= 本規約の中心)
- `cost_tracking/pricing.py` — 単価計算の純関数
- `cost_tracking/pricebook.py` — `data/pricebook.json` 読み込み
- `cost_tracking/records.py` — `CostRecord` dataclass + JSONL append
- `cost_tracking/estimator.py` — analyze pipeline の事前 cost 見積り
- `cost_tracking/report.py` — dashboard / CLI 集計 helper
- `data/pricebook.json` — 単価カタログ (運用者管理、git 追跡)
- `data/cost_records.jsonl` — 実コスト履歴 (git ignored)

---

最終更新: 2026-05-18
