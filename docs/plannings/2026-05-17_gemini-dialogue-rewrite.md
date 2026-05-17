# analyze pipeline で Gemini による台本本文の rewrite を統合

**日付**: 2026-05-17
**ブランチ**: `feat/gemini-dialogue-rewrite`
**前提**: PR #203 (= 参考動画から casting を切り離し) の上に乗る

---

## 1. 背景と目的

### 現状

analyze pipeline は Claude Opus 4.7 で参考動画から **構成・セリフ・感情** を
抽出する。Claude の出力は概ね「元動画の発話をそのまま字起こし → 抽象化」
の形をとる。`line.text` や `caption` は元動画の言い回しに近い表現が
そのまま残ることが多い。

CLAUDE.md 最重要ルールに既に記載されているとおり:

> `drafts/` の文字起こしを台本 JSON にそのままコピーしない (= 翻案権・著作権
> 侵害のリスク)。構成・アイデアは参考にしつつ、自分の言葉で書き直す

これは現状 **人間の責務** であり、構造的な担保が無い。

### 目的

analyze pipeline に **Gemini 2.5 Pro による rewrite phase** を組み込み、
Claude が抽出したセリフ + caption を「同じ意味・同じ感情で別の言い回し」
に自動変換する。これで著作権配慮を構造的に担保する。

### 方針 (= ユーザ確認済)

- **トグル**: **常に ON** (= analyze に完全統合)。env var `ANALYZE_DIALOGUE_REWRITE_ENABLED=0` だけ kill-switch として残す
- **対象**: `line.text` (= セリフ) + `caption` (= SNS 本文 + ハッシュタグ)
- **対象外**: `pronunciation_hints` / `speaker` / `emotion` / `delivery` / `audio_tags` / scene 構造 / `start` / `end`

## 2. データフロー

```
[参考動画]
  ↓ frames + transcript + acoustic features
[Claude Opus 4.7 inference]
  ↓ abstract screenplay (= 構成/セリフ/感情/casting 提案/etc.)
[NEW: Gemini 2.5 Pro rewrite] ← 本 PR で追加
  ↓ line.text + caption だけ書き換え (= 構造 / メタは全保持)
[validate + save to screenplays/auto_<sha>.json]
  ↓
[project 作成 → snapshot コピー → Stage 1 UI]
```

Gemini rewrite は **analyze phase の一部** として `claude` phase 完了直後、
`save` phase 直前に挿入される。SSE events に `phase_start: rewrite` /
`phase_complete: rewrite` (or `phase_skipped` 等) を流す。

## 3. Gemini prompt 設計

### 入力

```
あなたは台本リライト専門のエディタです。
他者の動画から抽出されたセリフを、意味と感情を保ったまま、
独自の言い回しで書き直してください。

# 入力 screenplay (= Claude が抽出した抽象台本)
{screenplay JSON}

# ルール
1. scene 数 / line 数 / line の順序は変えない
2. 各 line の `text` だけを書き換える (= 他の field は変更禁止)
3. 各 line の意味と感情 (= emotion field) を保持する
4. 各 line の文字数を **±20% 以内** に収める (= TTS 尺崩壊防止)
5. `caption` も同じ方針で書き換える (= 意味維持、独自の言い回し、ハッシュタグは
   そのまま / 等価な日本語タグに置換は OK)
6. ASCII の "," と "." を使わない (= 既存 validator 制約)。全角句読点を使う

# 出力
JSON で:
  {"caption": "<rewritten caption>",
   "lines": [{"text": "<rewritten line text>"}, ...]}
順序は入力 screenplay の line を flatten した順 (= scene 0 line 0,
scene 0 line 1, ..., scene 1 line 0, ...)。
```

### モデル

`gemini-2.5-pro` (= 品質優先、`config.GEMINI_REWRITE_MODEL` で上書き可)

### 温度

`temperature=0.7` (= 多少のバリエーション、暴走しない範囲)

## 4. 失敗時 fallback

| 失敗パターン                                          | 挙動                                                                                    |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `GOOGLE_API_KEY` 未設定                               | `phase_skipped: reason="no_api_key"` で Claude original を save (= warn ログのみ)       |
| `ANALYZE_DIALOGUE_REWRITE_ENABLED=0` env var          | `phase_skipped: reason="disabled"`                                                      |
| API timeout / 429 / quota                             | retry 2 回 → 全 fail なら `phase_skipped: reason="api_error"` + Claude original を save |
| JSON parse 失敗                                       | `phase_skipped: reason="parse_error"`                                                   |
| structure mismatch (= scene/line 数が違う、line 不足) | `phase_skipped: reason="structure_drift"`                                               |
| 文字数比率超過 (= ±20% 超え)                          | 該当 line のみ Claude original に戻す (graceful per-line fallback)                      |
| validator 違反 (= 全角句読点等)                       | 該当 line のみ Claude original に戻す                                                   |

**核心**: rewrite phase は **付加価値であり必須ではない**。失敗しても
analyze 全体は成功扱いとし、`metadata.json.dialogue_rewrite_status` に
"skipped" / "success" / "partial" を残して audit を可能にする。

## 5. 実装の触る場所

| ファイル                                                                             | 修正内容                                                                                                   |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| 新規 `gemini_dialogue_rewriter.py`                                                   | `rewrite_screenplay(sp, options=None) → (sp, usage, status)` (= API call + validation + per-line fallback) |
| `analyze/pipeline.py` (= L491-494 周辺)                                              | `claude` phase 完了直後に rewrite phase を挿入                                                             |
| 新規 `tests/test_gemini_dialogue_rewriter.py`                                        | API mock で 6+ scenarios のテスト                                                                          |
| `tests/test_analyze_pipeline.py` (既存)                                              | rewrite phase 統合の test 追加                                                                             |
| `data/pricebook.json`                                                                | `gemini-2.5-pro` の text input/output 単価を追加                                                           |
| `cost_tracking/recorder.py`                                                          | 新規 `record_dialogue_rewrite()` 関数                                                                      |
| `cost_tracking/pricing.py`                                                           | `compute_gemini_text_cost()` (= input + output token 単価計算)                                             |
| `CLAUDE.md` / `docs/abstract-screenplay-design.md` / `docs/developments/overview.md` | analyze pipeline の説明に rewrite phase を追記                                                             |

## 6. 不変条件 (= 守ること)

1. **structure 保持**: scene 数 / line 数 / line 順序は不変。違反したら全行 fallback
2. **メタ保持**: `speaker` / `emotion` / `delivery` / `audio_tags` / `pronunciation_hints` / `start` / `end` / `scene.location_ref` 等 **すべて touch しない**
3. **fail-soft**: rewrite 失敗で analyze 全体は失敗しない。original を save し audit field に残す
4. **idempotency**: 同じ入力 + 同じ Gemini model + 同じ温度 → 概ね同じ出力 (= 温度 > 0 で完全には保証されない、cache はしない)
5. **後方互換**: 既存 `screenplays/auto_<sha>.json` (= rewrite 前) はそのまま動く

## 7. cache 戦略

**cache しない**。理由:

- Gemini text rewrite は安価 (= 1 動画あたり ~\$0.02、Claude analyze の 1/12)
- `temperature=0.7` で完全な決定論性は無い → cache 比較が無意味
- 同じ参考動画から再 analyze する場面が稀

ただし **analyze 全体結果** (= `screenplays/auto_<sha>.json`) は既存どおり
sha cache される。同じ動画を re-analyze すると Claude も Gemini も再 call は走らない。

## 8. コスト試算

| 項目                  | tokens                              | 単価 (USD/M tok) | cost                |
| --------------------- | ----------------------------------- | ---------------- | ------------------- |
| Gemini 2.5 Pro input  | ~3,000 (= abstract screenplay JSON) | \$1.25           | \$0.00375           |
| Gemini 2.5 Pro output | ~3,000 (= rewritten text + caption) | \$5.00           | \$0.015             |
| **合計**              | —                                   | —                | **~\$0.019 / 動画** |

Claude analyze (= \$0.20 程度) の 10% 弱。許容範囲。

## 9. フェーズ分割

| Phase | 内容                                                     | 期待 diff size |
| ----- | -------------------------------------------------------- | -------------- |
| 0     | 設計 doc (本 doc)                                        | +200           |
| 1     | `gemini_dialogue_rewriter.py` 新規 + tests               | +400           |
| 2     | `analyze/pipeline.py` 統合 + tests                       | +150           |
| 3     | pricebook + recorder + pricing tests                     | +100           |
| 4     | docs (CLAUDE.md / abstract-screenplay-design / overview) | +50            |
| 5     | セルフレビュー + PR + merge                              | —              |

---

最終更新: 2026-05-17
