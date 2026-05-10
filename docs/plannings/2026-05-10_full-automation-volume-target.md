# フルオートモードで手動同等品質に到達するための累積生成本数

**日付**: 2026-05-10
**前提 doc**: `docs/plannings/2026-05-07_full-automation-feasibility.md` (= 実現可能性判定),
`docs/plannings/2026-05-07_full-automation-implementation-plan.md` (= Phase 0〜4 実装計画),
`docs/plannings/2026-05-09_quality-parity-auto-vs-manual.md` (= 軸 1〜8 品質パリティ計画)
**スコープ**: 計算結果の数値を 1 か所に固定する short note。新規実装タスクは含まない。

---

## 1. 目的

`scripts/auto_loop.py` の経路で生成された動画が、UI で人間が個別調整した
動画と「区別がつかない」レベル (= 手動同等) に到達するためには、運用上
**累積で何本生成しておくべきか** を、既存設計 doc の入口条件 / 出口 KPI
から逆算して固定する。

「品質パリティを実装すれば足りる」でも「本数を貯めれば足りる」でもなく、
**両方が揃ったときにのみ到達する** 構造を明示する。

---

## 2. 「手動と同じレベル」の定量定義

`quality-parity-auto-vs-manual.md §0.2` のゴール表 + `full-automation-implementation-plan.md §1` の
Phase 4 出口 KPI から:

| 指標                                          | 現状   | 「手動同等」のゴール                               |
| --------------------------------------------- | ------ | -------------------------------------------------- |
| auto_loop で「公開して問題ない」率            | 60-70% | **95%+**                                           |
| 手動介入が必要な比率 (= human gate reject 率) | 30-40% | **3-5%**                                           |
| 視覚要素 (BG / Kling / scene) の手動一致率    | 30-50% | 95%+                                               |
| 字幕の品質一致率 (= 画面幅収まり / 意味境界)  | 60%    | 90%+                                               |
| TTS の手動一致率                              | 30-50% | 75-85% (確率性で天井)                              |
| 本番運用検証                                  | 未     | **1 ヶ月、品質クレームゼロ、人間レビュー率 < 10%** |

これら全部を満たした地点を **「手動同等」** と呼ぶ。

完全一致 (= 100%) は ElevenLabs TTS の確率性 + 人間判断の主観性により
構造的に到達不可能 (= `quality-parity §5.1`)。

---

## 3. 軸ごとに必要な最低本数 (= ボトルネック分析)

各 Phase / 軸の入口条件を全部抽出して並べる:

| 軸 / Phase                               | 必要本数                                    | 出典                                        |
| ---------------------------------------- | ------------------------------------------- | ------------------------------------------- |
| Phase 0 計測基盤                         | 不良 ≥ 10 + 正常 ≥ 10 = **20 本**           | `full-automation-implementation-plan.md §2` |
| Phase 1 量産経路の安定                   | 7 日 × 3 本/日 = **21 本**                  | 同 §3                                       |
| Phase 2 入口 (不良サンプル蓄積)          | qa_failures **≥ 30 件**                     | 同 §4                                       |
| Phase 2 出口 (reject 率 < 5%)            | 直近 **30 本連続** で OK                    | 同 §4                                       |
| Phase 3 入口 (クリーン metrics)          | **≥ 50 本**                                 | 同 §5                                       |
| Phase 3 入口 (各 bandit 軸 ≥ 5 サンプル) | 5 値 × 4 軸 = **20 本** (理論最小)          | 同 §5 + `config.py:825-827` (`BANDIT_AXES`) |
| Phase 3 → Thompson sampling 移行         | **≥ 200 本**                                | 同 §5 D-3.2                                 |
| 軸 5: TTS パラメータ最適化               | **≥ 100 件**                                | `quality-parity §2.5`                       |
| 軸 8: scene-line 配分 cache 収束         | **約 10 件で収束**                          | 同 §2.8                                     |
| Phase 4 出口 (手動同等)                  | 1 ヶ月運用 = 1 日 5 本 × 30 日 = **150 本** | `full-automation-implementation-plan.md §6` |

ボトルネックは並べると以下の順:

1. **Phase 3 → Thompson sampling 移行 = 200 件** (= 任意の上振れ要件)
2. **Phase 4 検証 = 1 ヶ月運用 ≒ 150 本**
3. **軸 5 (TTS パラメータ最適化) = 100 件**
4. その他は累積 50-80 本までに吸収される

---

## 4. 累積必要本数の積算

各 Phase は「直前までの本数を含めて累積カウント」できる
(= 不良も正常もデータとして使える) ので、累積で見る:

| 通過時点                                  | 累積本数       | 内訳の根拠                                  |
| ----------------------------------------- | -------------- | ------------------------------------------- |
| Phase 0 完了 (計測ハーネスが正常稼働)     | **20 本**      | 手動 10 + reject 10                         |
| Phase 1 完了 (cron 7 日連続成功)          | **40-50 本**   | 21 本 + Phase 0 残 + Phase 2 用蓄積         |
| Phase 2 完了 (auto reject 率 < 5%)        | **60-80 本**   | qa_failures 30 件 + 直近 30 本連続          |
| Phase 3 active 化 (bandit が prompt 注入) | **100-130 本** | クリーン 50 + 各軸 5 サンプル + バッファ    |
| 軸 5 (TTS パラメータ最適化) 完了          | **150-180 本** | 解析対象 100 件は Phase 1〜3 で蓄積済を流用 |
| **Phase 4 完了 (≒ 手動同等)**             | **200-250 本** | 1 ヶ月運用検証分 (150 本) が上乗せ          |
| Thompson sampling 切替 (任意の上振れ)     | **400 本+**    | bandit を成熟させる場合                     |

---

## 5. 結論: 必要本数

**「手動と同じレベル」(= auto_loop 95%+ 公開可、人手介入 3-5%) に到達する
ための累積生成本数は、計算上 約 200 本** が現実的なライン。

内訳の理由:

- **下限** (= ぎりぎり Phase 4 の出口 KPI を満たす): **150 本**
  (= 1 ヶ月運用検証 = `1 日 5 本 × 30 日`)
- **実用ライン** (= bandit が安定 + TTS パラメータ最適化が効く): **200 本**
  (= 軸 5 の 100 件 + Phase 3 の bandit 軸別 5 サンプル × 4 軸 +
  クリーン 50 本 + 検証 50 本)
- **上振れ** (= bandit を Thompson sampling まで成熟): **400 本+**

---

## 6. 期間とコスト

`config.py:759-761` の env 既定値 + `feasibility.md §4` の単価で計算:

| 走らせ方                     | 1 日本数                 | 200 本到達まで            | API 課金 (1 本 $4.70 想定) |
| ---------------------------- | ------------------------ | ------------------------- | -------------------------- |
| 控えめ (`DAILY_VIDEO_CAP=3`) | 3 本                     | **約 67 日 (≒ 2.2 ヶ月)** | $940                       |
| 既定 (`DAILY_VIDEO_CAP=5`)   | 5 本                     | **約 40 日 (≒ 5.7 週)**   | $940                       |
| `DAILY_COST_CAP_USD=20` 枠内 | 4 本/日 ($18.8/日 ≤ $20) | **約 50 日**              | $940                       |

月次コスト: 1 日 5 本 = $23.5/日 = **約 $700/月** (`feasibility.md §4`)。

cap は `config.py:757-761`:

```python
DAILY_COST_CAP_USD   = 20    # env DAILY_COST_CAP_USD
MONTHLY_COST_CAP_USD = 300   # env MONTHLY_COST_CAP_USD
DAILY_VIDEO_CAP      = 5     # env DAILY_VIDEO_CAP
```

`scripts/auto_loop.py:_budget_guard()` がこれらを冒頭で fail-fast。

---

## 7. 重要な留保: 両輪原則

この「200 本」は計画書の入口条件・出口 KPI を **数式的に積算** した結果で、
以下の前提に立っている:

1. **Phase 1〜4 の実装が完了していること**
   → 2026-05-10 時点で ✅ 完了済
   (= `9dc9e84` (Phase 1), `c6098fd` (Phase 2), `c1e4811` (Phase 3),
   `1d5d9c5` (Phase 4 = approve_gate CLI))
2. **`quality-parity-auto-vs-manual.md` の Phase 1〜8 (軸 1〜8) が
   並行実装されていること**
   → 2026-05-10 時点で ❌ 未着手 (= 進捗トラッキング表が全部 "-")

つまり、現状コード (= 軸 3 / 軸 5 / 軸 6 / 軸 8 が未実装) のまま 200 本貯めても、
auto_loop の品質一致率は **60-70% で頭打ち** (= quality-parity ドキュメントの
「現状」値) になり、手動同等には到達しない。

「200 本生成」と「軸 1〜8 の実装」は **両輪**:

- 実装が先行していて本数が足りないケース
  → 軸 5 の 100 件解析が組めない、bandit が exploit できない
- 本数だけ貯めて実装が遅れるケース
  → 軸 3 (post-processing 内製) が無いので「BGM 無し / intro 無し」の
  動画が量産される

---

## 8. 一行サマリ

**現実的な目標: 累計 約 200 本 (1 日 5 本ペースで約 40 日、API 課金約 $940)**。
ただし `quality-parity-auto-vs-manual.md` の **軸 1〜8 の実装と並行で貯める** こと。
本数だけ先行しても 60-70% で頭打ち、実装だけ進めても A/B 検定の
有意差検出に必要なサンプルが集まらない。

---

## 9. 関連ファイル

### 設計 doc

- `docs/plannings/2026-05-07_full-automation-feasibility.md` — 実現可能性判定 + Phase 1 実装スケッチ
- `docs/plannings/2026-05-07_full-automation-implementation-plan.md` — Phase 0〜4 詳細計画 (= 入口条件 / 出口 KPI / タスク / ロールバック)
- `docs/plannings/2026-05-09_quality-parity-auto-vs-manual.md` — 軸 1〜8 (= テンプレ / TTS hybrid cache / post-processing / 品質ゲート / TTS チューニング / 字幕分割 / 部品スコアリング / scene-line 配分)

### 実装エントリポイント

- `scripts/auto_loop.py:333-458` — `run_one_video()` (= 1 動画分の orchestrator)
- `scripts/auto_loop.py:56` — `INTERNAL_STAGES = ("tts","bg","kling","scene","overlay")`
- `scripts/approve_gate.py` — `awaiting_human_gate` 状態の CLI 承認 / 却下
- `improvement/strategy.py` — `select_assignments_for_video()` / `record_assignments()` (= bandit dispatch)
- `improvement/bandit.py` — ε-greedy 実装
- `qa/registry.py:run_validators_for_stage()` — stage 別 validator dispatch

### 安全装置 (= `config.py`)

- L757-761: `DAILY_COST_CAP_USD` / `MONTHLY_COST_CAP_USD` / `DAILY_VIDEO_CAP`
- L765: `AUTO_LOOP_ALLOW_PUBLIC` (= unlisted 強制 gate)
- L774-775: `AUTO_LOOP_STAGE_SOFT_LIMIT_SEC` (= soft limit / Slack warning)
- L779-787: `QA_VALIDATORS_ENABLED` / `QA_VALIDATOR_BLACKLIST`
- L792-798: `QA_RETRY_LIMITS` (= stage 別 retry 上限)
- L806-818: `IMPROVEMENT_STRATEGY` (= baseline / shadow / active)
- L821: `BANDIT_EPSILON` (= 0.2)
- L825-827: `BANDIT_AXES` (= hook_type / tone / dominant_emotion / theme)
- L834-836: `PRODUCTION_HUMAN_GATE_ENABLED` (= publish 直前停止 gate)
