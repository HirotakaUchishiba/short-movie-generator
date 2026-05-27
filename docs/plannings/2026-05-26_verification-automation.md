# 確認作業の自動化と人間レビューゼロの完全自律自走設計

最終更新: 2026-05-26
ステータス: ドラフト (未実装)
安全モデル: **完全無制限** (= ユーザー決定 2026-05-26。permission / マージ / 公開のゲートを設けない)

## 1. 背景と目的

### 現状の課題

1. コード修正のたびに、成果物を人間が「動画を再生し」「音声を試聴し」「字幕を目視し」「UI を操作して」確認している。特に **字幕の表示時刻と実発話時刻が合っているか** は毎回プレビュー再生で照合しており非効率。
2. 字幕↔音声タイミングは退行が起きやすい (= 頭切れ / char_ts ズレ / snap / 手打ちミス)。目視は見落とす。
3. 既に `qa/` validator 基盤と `auto_loop.py` の自己修正ループがあるが、**字幕表示時刻 vs 実発話時刻を検証する validator が無い**。
4. **最終目的は「人間を一切介在させず、大きなタスクを完遂まで自律自走する」こと**。人間の介入点 ― ツール実行の **許可** / 変更の **レビュー** / コミット・**マージ判断** / **公開判断** ― を全て撤廃する。

### 解決策 — 人間の全介入点を撤廃する (完全無制限)

ユーザー決定により、ゲートを設けず人間の介入点を全廃する:

| 人間の介入点          | 置換                                     | 安全装置                           |
| --------------------- | ---------------------------------------- | ---------------------------------- |
| ツール実行の許可      | 全権限許可 (プロンプト・`deny` とも無し) | なし                               |
| 変更のレビュー        | 全体最適レビューエージェント + 客観検証  | レビューが **唯一の品質関門**      |
| コミット / マージ判断 | レビュー approve で即マージ              | なし (branch protection 無し)      |
| 公開判断              | 自動公開                                 | なし (予算上限・unlisted 強制無し) |

人間の「目視・試聴」は成果物を直接解析する validator に置換する (= ファイル解析主軸。字幕↔音声は char_ts / Whisper の 2 段。§3.1-3.4)。

> **設計者注記 (faithful reporting)**: 完全無制限では、誤マージ・誤公開・暴走課金が起きても **自動では止まらない**。唯一の防御線は「全体最適レビューエージェントの判定精度」と「運用者の手動監視 (`/usage` / `Escape`)」。これは CLAUDE.md「コストのかかる操作を安易に実行しない」と緊張関係にある (= ユーザーの明示決定で上書き)。`--max-budget-usd` / CI マージ阻止は "人間の介在" ではなく自走を止めない自動ブレーキなので、後から戻す余地は残す (§8)。

### `/goal` コマンドの正確な仕様 (前提知識)

Claude Code v2.1.139+ の公式機能。`/goal <完了条件>` で条件達成まで自律継続。

- **完了判定**: 小型モデル (既定 Haiku) が「条件文 + 会話履歴」を評価し yes/no。**ツール不可・会話出力のみで判定**。
- **完全自律**: Auto Mode がターン内のツール承認を、`/goal` がターン間の手動操作を省く。
- **上限 (任意)**: "or stop after N turns" / `--max-turns` / `--max-budget-usd`。
- **制約**: 1 セッション 1 ゴール。`disableAllHooks` 下で不可 (= 本プロジェクトは利用可)。`claude -c` / `-r` で復元可。

→ 最重要含意: **完了条件は会話出力で証明できる客観指標にする**。「テストが通る」でなく「`pytest` を実行し終了コード 0 を出力させる」。

### 今回のスコープ

全体像を描き Phase で分離。**Phase 1 (字幕タイミング char_ts validator) から着手**。検証 (Phase 1-3) が自走 (Phase 4) の前提。

やらないこと:

- 字幕タイミングの **決定** ロジックの変更 (= char_ts ベースのまま。検証を足すだけ)。
- 検証・自走のための動画 / 背景 / TTS / リップシンク再生成 (= API 課金。validator は既存成果物を読むだけ)。
- analyze の Whisper 出力 (= 参考動画の別音声) の流用 (§3.5)。

## 2. アーキテクチャ設計

### 全体像: 自律自走ループ (無制限)

```
  ┌─────────────── /goal + Auto Mode + 全権限許可 (ゲートなし) ───────────────┐
  │                                                                            │
  │  [実装エージェント] ──feature ブランチで修正 + commit──▶ [検証ステップ]    │
  │        ▲                                              pytest / ruff / validator │
  │        │                                                        │            │
  │        │                                          [全体最適レビューエージェント] │
  │        │                                       CLAUDE.md 最重要ルール +      │
  │        │                                       architecture + code-review +  │
  │        │                                       security-review + 影響範囲     │
  │        │                                                        │            │
  │        └──── request changes (指摘 + fail を読み再修正) ◀───────┤            │
  │                                                                 │ approve     │
  │                                                                 ▼ 即          │
  │                                                          自動マージ (squash) → 自動公開 │
  └────────── 完了条件 (全 PR マージ済 + テスト緑 + validator fail 0) を会話出力で証明 ──────┘
```

無制限モードでは branch protection / 公開ゲートが無いため、**レビュー approve がそのまま即マージ・自動公開につながる**。よってレビューエージェントの判定精度が品質と安全の全てを担う (§3.7)。

### 検証レイヤと既存資産

| レイヤ                 | 検証する「人間の確認」            | 入力成果物                 | 手法                    | 課金            | Phase |
| ---------------------- | --------------------------------- | -------------------------- | ----------------------- | --------------- | ----- |
| char_ts 字幕タイミング | 字幕と音声がズレていないか (常時) | `tts_full.json` + snapshot | char_ts 照合            | ゼロ            | 1     |
| Whisper 出口実測       | 完成動画で字幕と発話が合うか      | `reels_<TS>.mp4`           | Whisper word ts 照合    | API or ローカル | 2     |
| OCR フレーム可読性     | 字幕が画面内・読めるか            | `overlaid.mp4`             | ffmpeg + tesseract      | ゼロ            | 2     |
| UI 生存確認            | UI が壊れていないか               | preview UI                 | run/verify → Playwright | ゼロ            | 3     |

### 追加・変更箇所

```
qa/validators/subtitle_timing.py / subtitle_audio_sync.py / subtitle_render.py  ← 新規 validator
qa/registry.py / qa/categories.py / config/qa.py  ← 登録 + タグ + 閾値
.claude/settings.json (permissions 全許可)         ← 全権限許可                  [Phase 4]
docs/plannings/...-autonomous-loop-runbook.md       ← 自走 + 自動マージ runbook  [Phase 4]
```

### 依存 (既存資産の再利用)

- `whisper_client` / `stages/text_mapping` / `compositor` — 検証ロジックの入力。
- `qa.registry` / `qa.recorder` / `auto_loop.py` — validator 実行基盤。
- `code-review` / `security-review` / `analyze-refactoring` — Claude Code 組み込みのレビュー / 全体調査スキル。
- `.github/workflows/ci.yml` (`ruff check` + pytest) — 客観検証 (参考情報として走らせる)。
- `gh` CLI (PR 作成・レビュー・マージ) / `commit-push` スキル。
- **Codex CLI** (= 異種モデル cross-critique 用、Phase 4)。Claude Code とは別 CLI として並行運用し、実装 = Claude / レビュー = Codex の役割分担で盲点共有を断つ (§3.7)。

## 3. 実装設計

### 3.1 字幕タイミング validator (char_ts ベース) — `subtitle_timing`

- **stage**: overlay。**責務**: 確定字幕タイミング (line.start/end・手動 `subtitles[]`) と char_ts 実発話時刻のズレを per-line / per-chunk で測り `subtitle_timing_off` で fail。char_ts 不在 / per-voice 欠落は skip。
- **トートロジー回避**: 対象は chunk 配分出力でなく、char_ts と独立な入力 (snap 結果の line.start/end・手打ち) の妥当性。**課金ゼロ**。

### 3.2 字幕↔音声 validator (Whisper 出口実測) — `subtitle_audio_sync`

- **stage**: overlay (既定 OFF、リリース前のみ)。**責務**: `reels_<TS>.mp4` 音声を Whisper 再文字起こし → 焼き込み字幕を緩くアライメント → 表示時刻と発話区間のズレを測る。char_ts から独立した出口実測。**動画再生成なし**。

### 3.3 overlay 後フレーム validator (視覚検証) — `subtitle_render` [Phase 5 実装済み]

- `overlaid.mp4` から複数時刻でフレーム抽出 → **opencv の Canny エッジ密度**で字幕帯 (下 1/3) にテキスト様要素があるか実測 (= tesseract 非依存)。tesseract があれば OCR で文字も読み補強。実 overlaid.mp4 で動作確認済み。**課金ゼロ**。

### 3.4 UI 生存確認 (Playwright) — `scripts/e2e_ui_check.py` [Phase 6 実装済み]

- preview_server + frontend/dist を起動し Playwright (chromium) で UI を操作・スクショ取得。「UI が壊れていないか」(= 配信・描画される) の生存確認に限定。動画の正しさは 3.1-3.3 が担うので E2E は薄く保つ。実走確認済み (title 取得・`#root` 描画・スクショ保存)。

### 3.5 Whisper の使い分け (決定 vs 検証)

1. analyze (既存): 参考動画音声 → 抽象台本生成。
2. 字幕タイミングの **決定** (使わない): char_ts を使う。参考動画 Whisper は別話者・別テキストで流用不可。
3. 字幕タイミングの **検証** (本設計 3.2): 完成 **TTS 音声** を新規 Whisper。2 とは対象音声が異なるため矛盾しない。

### 3.6 自走オーケストレーションと権限設計 (完全無制限) [Phase 4]

- **ループ**: 実装 → 検証ステップ (pytest / ruff / overlay 再合成 + validator、結果を会話出力) → 全体最適レビュー → request changes なら再修正 / approve なら即マージ → 完了条件まで反復。
- **権限**: Auto Mode + `.claude/settings.json` の `permissions` を全許可 (`deny` を設けない)。プロンプトは出ない。
- **完了条件の雛形** (会話出力で証明可能):
  ```
  /goal 対象の修正について feature ブランチで PR を作り、CI (ruff + pytest) が緑、
  全体最適レビューが approve、subtitle_timing validator が fail 0 件であることを
  各コマンド出力で示した上で squash マージせよ。
  ```
- **歯止め**: ゲートを設けないため、唯一の歯止めは運用者の手動監視 ― `/usage` で課金確認、`Escape` / `/goal clear` で中断。`--max-turns` / `--max-budget-usd` を付けるかは任意 (= 付ければ自動ブレーキになるが、ユーザー決定では既定では設けない)。

### 3.7 全体最適レビューエージェント (品質と安全の唯一の関門) [Phase 4]

無制限モードでは branch protection が無く **approve = 即マージ = 即公開**。よってこのレビューの判定精度が全てを担う。**局所の正しさだけでなく「全体最適」を判断基準にする**:

- **入力**: PR diff + `CLAUDE.md` (最重要ルール) + `docs/developments/architecture.md` (レイヤ・依存方向) + `coding-rules.md`。
- **観点** (この順で総合判定):
  1. **プロジェクト最重要ルール適合**: 特定台本へのハードコードでないか (汎用性)、コスト操作を乱発しないか、指示スコープを超えないか。
  2. **全体整合性**: アーキテクチャのレイヤ・依存方向を壊さないか、既存の抽象と重複・分裂を生まないか。
  3. **局所的正しさ**: `code-review` (correctness bug)、外部入力を扱うなら `security-review`。
  4. **影響範囲**: `Explore` / `analyze-refactoring` で退行候補・波及先を洗う。
  5. **保守性**: 将来の拡張を妨げないか。
- **判定**: approve / request changes を **会話に明示出力** (= `/goal` 完了条件が参照)。
- **盲点共有対策 (最重要)**: 同一モデル同士のレビューは同じ誤りを見逃しうる。よってレビューは必ず **客観検証 (pytest / validator / 型) に接地** させ、合格を「テスト緑 + validator fail 0」で定義する。無制限モードでは自動ブレーキが無いぶん、この接地が誤マージ・誤公開を防ぐ事実上の最後の砦になる。
- **異種モデルによる cross-critique (盲点共有の本命対策)**: 接地だけでは同一モデルの盲点を消し切れない。レビューを **異なる基盤モデル** に担わせる ― 実装を Claude Code、cross-critique を **Codex CLI (= GPT 系)** に振り、SLEAN 型の independent → cross-critique → arbitration (= 客観検証で決着) を回す。根拠: 異種 LLM アンサンブルはバグ検出 +10〜12% / multi-file recall +18%、同種アンサンブルは synergy 減少 (§9)。役割: Claude = 設計・複雑機能 (SWE-bench 80.9%) / Codex = 自律実行・端末・トークン 4 倍効率 (Terminal-Bench 77.3%)。Codex の full-auto (gate なし) は完全無制限志向と親和的。**導入時期**: Phase 1-3 で検証 validator の土台 (= arbitration の客観面) を作ってから。土台無しに異種を足しても主観多様性だけでは不十分。

### 3.8 自動マージ・公開 (即時) [Phase 4]

- レビュー approve で即 squash マージ (= 履歴単純化・revert 容易)。branch protection は設けない (CI は参考情報として走るがマージを阻止しない)。
- 公開も自動 (Stage 8)。予算上限・unlisted 強制は設けない。
- request changes は実装エージェントへ戻し `/goal` ループで再修正。

### 3.9 自走スコープ (無制限)

| 自走対象                        | 可逆性 / コスト    | 扱い                                                                    |
| ------------------------------- | ------------------ | ----------------------------------------------------------------------- |
| 開発タスク (コード修正・マージ) | 可逆 (git revert)  | レビュー approve で即マージ                                             |
| 動画生成 (Stage 1-6)            | API 課金           | retry 上限は任意。自走は再生成しない方針 (= validator は既存成果物のみ) |
| 公開 (Stage 8)                  | **不可逆・外向き** | 自動公開 (ゲートなし)。誤公開は手動監視でのみ検知                       |

## 4. コスト (無制限モードの含意)

- validator 自体は外部 API 課金ゼロ (ローカル ffmpeg / PIL / tesseract / faster-whisper)。Whisper 出口のみ既定 OFF・リリース前。
- **検証・自走のために動画 / 背景 / TTS / リップシンクを再生成しない** (= 是正は overlay 再合成のみ)。これは validator の設計上の性質であり、無制限モードでも維持される。
- 一方、自走全体の **予算上限・公開ゲートは設けない** (ユーザー決定)。CLAUDE.md のコストルールとは緊張関係にあり、手動監視 (`/usage` / `Escape`) が唯一の歯止め。

## 5. テスト方針

- 単体: char_ts / Whisper / OCR validator が各々のズレ・不備を検出し、依存欠落で skip すること。
- 統合: `run_validators_for_stage("overlay")` に新 validator が乗り fail が `qa_failures` に記録されること。
- 自走 dry-run: `--max-turns` を小さくし「検証 → レビュー → 再修正 → PR → マージ」の 1 巡が回ることを確認 (= 完了条件の証明可能性を検証)。
- 手動: 実プロジェクトで字幕タイミング問題を validator が捕捉 (overlay 再合成のみ、AI 課金なし)。

## 6. 運用設計

- char_ts validator は auto_loop / preview_server の overlay stage 後に常時実行。Whisper はリリース前に明示起動。
- `qa/eval_validators.py` で tag 別 recall / precision を週次集計し閾値調整。
- 自走の起動・監視・中断は §3.6 (`/goal` + `/usage` + `Escape` + `claude -c`/`-r`)。無制限モードでは `/usage` での課金監視が事実上必須。

## 7. 実装タスク

### Phase 1: 字幕タイミング char_ts validator (自走の合否判定の土台)

- [ ] 1. `subtitle_timing_off` タグを `qa/categories.py` に追加
- [ ] 2. `qa/validators/subtitle_timing.py` 新規 + 単体テスト
- [ ] 3. `qa/registry.py` overlay 登録 / `config/qa.py` 閾値
- [ ] 4. 実プロジェクトで手動確認 (overlay 再合成のみ)

### Phase 2: 出口実測 (Whisper + OCR)

- [ ] 5. `subtitle_audio_sync.py` (Whisper 出口) + 既定 blacklist + テスト
- [ ] 6. `subtitle_render.py` (OCR) + tesseract optional 化 + テスト

### Phase 3: UI 生存確認

- [ ] 7. run/verify での主要導線確認手順を runbook 化
- [ ] 8. (必要なら) Playwright E2E を `frontend/` に導入

### Phase 4: 人間レビューゼロの完全自律自走

- [ ] 9. `.claude/settings.json` を全権限許可に設定 (§3.6)
- [ ] 10. 全体最適レビューエージェントの役割・観点を runbook 化 (§3.7)
- [ ] 11. 完了条件雛形集 + 自走 runbook 作成 (即マージ・自動公開のフロー)
- [ ] 12. 自走 dry-run で 1 巡を検証
- [ ] 13. 異種モデル cross-critique (Codex CLI) の導入: 実装 = Claude / レビュー = Codex の SLEAN 型 3 フェーズ (independent → cross-critique → arbitration) を runbook 化 (§3.7)。検証 validator の土台 (Phase 1-3) 完成後に着手

### Phase 5: FFmpeg 動画視覚検証の実動作 (実装済み 2026-05-27)

- [x] 14. `subtitle_render` を opencv エッジ密度ベースに実装 (= tesseract 非依存・複数フレームサンプルで字幕の出/消を跨ぐ)。tesseract があれば OCR で補強
- [x] 15. 実 `overlaid.mp4` で動作確認 (max_edge_density=0.024 で pass。OCR は縁取り字幕で空振り → エッジ密度を主経路にした設計の妥当性を実証)

### Phase 6: UI E2E (Playwright Python) (実装済み 2026-05-27)

- [x] 16. `scripts/e2e_ui_check.py`: preview_server 起動 + chromium で UI 操作 + スクショ取得
- [x] 17. 実走確認 (title 取得・`#root` 描画・スクショ 133KB 保存)

## 8. リスクと対策

- **完全無制限の不可逆リスク (最重要)**: 誤マージ・誤公開・暴走課金が起きても自動では止まらない。防御線は「全体最適レビューエージェントの判定精度」(§3.7) と「運用者の手動監視」(`/usage` / `Escape`) のみ。レビューが見逃せば壊れたコードが main に入り本番公開されうる。
  - 緩和の余地 (= 後から戻せる、いずれも人間を介在させない自動ブレーキ): `--max-budget-usd` で課金上限、CI を required check 化してマージ阻止、公開のみ `AUTO_LOOP_ALLOW_PUBLIC=0` で unlisted 強制。理念 (人間が一切介在しない) を損なわずに不可逆事故だけ防げる。採否はユーザー判断。
- **エージェント相互レビューの盲点共有**: 客観検証に接地し合格を数値で定義 (§3.7)。
- **`/goal` 評価モデルの限界**: ツール不可・テキストのみ判定 → 完了条件は会話出力で証明可能な客観指標に限定。
- **char_ts 検証のトートロジー**: line.start/end・手打ちを対象にし独立性を確保。真の char_ts ズレは Whisper 出口で担保。
- **Whisper アライメント不安定**: 緩いアライメント + 不能 chunk は warning。閾値は eval で調整。
- **退行**: 字幕決定ロジックは不変。validator 追加のみ。config blacklist で個別 OFF 可能。

## 9. 参考資料

- `docs/plannings/2026-05-26_subtitle-char-ts-timing.md` — 字幕タイミングの **決定** (char_ts)。本設計は「決定」に「検証」を足す
- `/goal` コマンド解説: https://zenn.dev/suwash/articles/claude-code-goal-command_20260514
- `qa/registry.py` / `qa/recorder.py` / `qa/categories.py` — validator 基盤
- `scripts/auto_loop.py` `_validate_stage` / `_retry_failed_scenes` — 自己修正ループ (自走の原型)
- `whisper_client.py` / `compositor.py` `_load_char_timing` — 検証対象の char_ts 経路
- `.github/workflows/ci.yml` — 客観検証の既存土台
- CLAUDE.md「字幕の手動チャンク制御」「コストのかかる操作を安易に実行しない」「段階的ゲート方式」
- 異種モデル相互レビューの根拠: [Diverse LLMs vs. Vulnerabilities](https://arxiv.org/pdf/2512.12536) (検出 +10〜12% / recall +18%) / [Diversity Empowers Intelligence](https://arxiv.org/pdf/2408.07060) (同種は synergy 減少) / [SLEAN — 3 フェーズ ensemble](https://arxiv.org/pdf/2510.10010)
- Codex CLI vs Claude Code 比較 (2026-05): [morphllm](https://www.morphllm.com/comparisons/codex-vs-claude-code) / [NxCode](https://www.nxcode.io/resources/news/claude-code-vs-codex-cli-terminal-coding-comparison-2026)
