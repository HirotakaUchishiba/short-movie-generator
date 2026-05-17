# analyze による casting 自動提案 (登場人物 / 話者 / 感情)

> **作成日**: 2026-05-15
> **発端**: 「動画から台本化する際、誰がどんな感情で喋っているかは読み取れるはず。登場人物・話者・感情の選定も自動化し、間違っていたら人間が直せる UI にしたい」というユーザ要望。
>
> ⚠️ **2026-05-17 補足**: 本 doc が提案した「appearance 突合による自動 casting」は方針変更で
> 撤廃された (= `docs/plannings/2026-05-17_decouple-casting-from-reference.md`)。
> 現行は「catalog の base から alphabetical 順に割当てる単純割当 + Stage 1 UI で人間が自由
> に選び直す」方式。`speaker_profiles` 検出と pre-fill 機構そのものは維持されている。

## WHY (= なぜやるか)

### 現状の整理 (= 何が auto で何が manual か)

調査の結果、ユーザが挙げた 3 項目の現状はこうなっている:

| 項目                                                             | 現状          | 備考                                                                                                             |
| ---------------------------------------------------------------- | ------------- | ---------------------------------------------------------------------------------------------------------------- |
| **感情** (`lines[].emotion`)                                     | **既に auto** | analyze の SYSTEM_PROMPT が「各 line に emotion を必ず埋める」と指示済み。Stage 1 にドロップダウン編集 UI もある |
| **話者** — 匿名グルーピング (`lines[].speaker` = `speaker_1` 等) | **既に auto** | analyze がフレーム解析で「誰が喋っているか」を匿名 ID で識別済み                                                 |
| **話者** — 実キャラへの対応付け (`speaker_to_ref`)               | **手動**      | `speaker_1 → f1__office` のマッピングは Stage 1 の 🎙 話者マッピングで人が毎回ゼロから設定                       |
| **登場人物** (`featured_characters`)                             | **手動**      | 動画に出るキャラ集合は Stage 1 の 👥 登場人物で人が毎回ゼロから設定                                              |

つまり **真の手動ギャップは `featured_characters` と `speaker_to_ref` の 2 つ**。emotion と匿名 speaker 検出は既に自動化済み。

### なぜ casting だけ手動なのか (= 既存設計の意図)

`docs/abstract-screenplay-design.md` の設計思想は「元動画をクローンせず、構成・セリフ・感情だけ抽出して **自分のキャラ** で作り直す」。参考動画に映っている人物と、ユーザのキャラライブラリ (`f1`, `m1` 等) は **別物** なので、「speaker_1 = どのキャラか」に客観的な正解は無く、creative な casting 判断とされてきた。SYSTEM_PROMPT も `featured_characters` / `speaker_to_ref` の出力を明示禁止している。

### 解決の方針

casting に「唯一の正解」が無いのは事実だが、**参考動画から「speaker_1 は若い女性で明るい話し方」といった profile は読み取れる**。これを使って analyze が **best-effort の casting 提案**を出し、人間が訂正する 2 段構えにすれば、毎回ゼロから設定する手間が消える。「提案 → 訂正」は location_ref / visual_intent と同じパターンで、既存アーキテクチャと整合する。

## WHAT (= 修正の最終形)

### 1. analyze が `speaker_profiles` を検出する

abstract 台本の root に新フィールド `speaker_profiles` を追加。匿名 speaker ごとに参考動画から読み取った profile を持つ:

```jsonc
"speaker_profiles": {
  "speaker_1": { "gender": "female", "age_range": "20s", "description": "明るく早口、リアクション大きめ" },
  "speaker_2": { "gender": "male", "age_range": "40s", "description": "落ち着いた低めの声、ゆっくり" }
}
```

`gender` / `age_range` / `description` はすべて optional。analyze がフレーム + 音響特徴から推論する。単一人物動画で speaker タグが無い場合は `speaker_profiles` 自体を省略。

### 2. character library に optional な `appearance` metadata を追加

`characters/<base>/voice.json` (= `CharacterMeta`) に optional な `appearance` を追加:

```jsonc
{
  "id": "f1",
  "voice_overrides": { ... },
  "appearance": { "gender": "female", "age_range": "20s", "description": "黒髪ロング、オフィスカジュアル" }
}
```

これは speaker_profiles とのマッチ精度を上げるためのヒント。**無くても本機能は動く** (= analyze は appearance 不在のキャラも候補に含め、ID や他の手がかりで提案する)。

### 3. analyze が `featured_characters` + `speaker_to_ref` を自動提案する

`location_catalog` / `intent_catalog` と同じパターンで、analyze pipeline が character library を catalog として Claude に渡す。catalog があるとき:

- Claude は検出した `speaker_profiles` を character catalog の `appearance` と突合し、最も近いキャラを選ぶ
- `featured_characters` (= 使うキャラ集合) と `speaker_to_ref` (= speaker_N → resolved character ref) を出力する
- catalog が無い / 空のときは従来どおり出力しない (= 完全手動にフォールバック)

post-processing で検証する:

- catalog に存在しない ref は drop (= 提案から除外)
- speaker をどのキャラにも対応付けられなければ、その speaker は `speaker_to_ref` から省略 (= 未マッピングのまま人間に委ねる)
- `featured_characters` は `speaker_to_ref` の値 + Claude が挙げた追加キャラの和集合を、catalog 実在チェックして確定

### 4. Stage 1 UI — 推定の可視化 + 訂正導線

`featured_characters` / `speaker_to_ref` は abstract に入るので、**既存の 👥 登場人物 / 🎙 話者マッピング セクションが自動的に pre-fill された状態で表示される** (= 既存 UI がそのまま訂正導線になる。新規エディタは不要)。追加するのは:

- 🎙 話者マッピングの各 speaker 行に `speaker_profiles` のヒントを表示 (例: 「speaker_1 — female / 20s / 明るく早口」)。人間がマッピングを判断しやすくする
- 「✨ analyze 推定」バッジ — featured_characters / speaker_to_ref が analyze 由来 (= 未確認の提案) であることを示す。人間が触れば通常の手動値になる

### 5. 感情 — 既に auto。本機能では新規検出なし

`lines[].emotion` は既に analyze が産出し、Stage 1 にドロップダウン編集 UI もある。本機能では **emotion の検出ロジックは触らない**。設計書として「emotion は既に自動 + 訂正可能」である事実を明記し、UI が機能していることを確認するに留める。

## scope 外 (= 本機能で踏み込まないこと)

- **顔認識 / 声紋による厳密マッチング** — speaker_profiles と appearance はあくまで自然言語 profile の突合。embedding ベースの厳密照合は将来課題
- **character 管理 UI** — `appearance` metadata を編集する専用 UI は作らない。`voice.json` への手編集 or 既存の character 追加経路で設定する想定。本機能は appearance 不在でも graceful に動く
- **emotion の検出ロジック変更** — 既に auto なので触らない
- **匿名 speaker 検出ロジック変更** — 既に auto なので触らない

## HOW (= phase 分解)

全 4 phase、本セッション内で順次実装する (= worktree `feat/analyze-auto-casting` 上)。

### Phase 1: character appearance metadata

| 対象                                          | 内容                                                                                                                                                                                             |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `analyze/character_meta.py`                   | `CharacterMeta` に `appearance: dict` (optional) を追加。`to_dict` / `from_dict` 対応。`build_character_catalog()` を新設 (= 全 base の id + appearance + 利用可能 wardrobe を dict list で返す) |
| `tests/test_character_meta.py` (or 既存 test) | appearance の round-trip、`build_character_catalog` の正常系 / 空 / 壊れ json skip                                                                                                               |

### Phase 2: analyze speaker_profiles 検出 + casting 提案

| 対象                           | 内容                                                                                                                                                                                                                                                                                                               |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `video_analyzer.py`            | SYSTEM_PROMPT: `speaker_profiles` を出力スキーマに追加 + character catalog 提供時は `featured_characters` / `speaker_to_ref` を提案 (= 「絶対に出力しない」リストから条件付きで解放)。`build_screenplay` に `character_catalog` 引数 + catalog 注入ブロック + post-processing (実在検証 / 未マッチ speaker の省略) |
| `analyze/pipeline.py`          | `build_character_catalog()` を load して `build_screenplay` に渡す。progress event に `character_catalog_size` を追加                                                                                                                                                                                              |
| `tests/test_video_analyzer.py` | catalog 注入、speaker_profiles 通過、casting 提案の post-processing (実在しない ref の drop / 未マッチ speaker の省略 / catalog 無しで従来挙動)                                                                                                                                                                    |

### Phase 3: validator + types 対応

| 対象                      | 内容                                                                                                                         |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `screenplay_validator.py` | SCHEMA に root `speaker_profiles` (object) を追加。`featured_characters` / `speaker_to_ref` は既に schema にあるので変更不要 |
| `frontend/src/types.ts`   | `AbstractScreenplay` に `speaker_profiles?` を追加。profile の型を定義                                                       |
| 関連 test                 | speaker_profiles を持つ screenplay が validator を通る / 不正な型を弾く                                                      |

### Phase 4: Stage 1 UI (推定の可視化 + 訂正導線)

| 対象                                                 | 内容                                                                                                                                                                |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/components/stages/ScriptEditPanel.tsx` | 🎙 話者マッピングの各 speaker 行に `speaker_profiles` のヒント表示。👥/🎙 セクションに「✨ analyze 推定」バッジ (= abstract に値があり、かつ人間未編集のときに表示) |
| frontend test                                        | profile ヒントの表示、バッジの表示条件                                                                                                                              |

## 不変条件 (= 守るべきルール)

1. **提案は best-effort**。analyze は casting 提案に失敗しても fail しない (= `featured_characters` / `speaker_to_ref` が空でも従来どおり手動で進められる)
2. **人間の訂正が常に最優先**。既存の 👥 登場人物 / 🎙 話者マッピング 編集 UI を温存し、提案は初期値として入れるだけ。人間が触ったら通常の手動値
3. **emotion / 匿名 speaker 検出は不変**。既に auto なので検出ロジックを触らない
4. **character `appearance` は optional**。metadata 不在でも機能は graceful に動く (= analyze は appearance 無しキャラも候補にする)
5. **catalog 無し = 完全手動フォールバック**。`characters/` が空なら従来どおり (= 提案なし、手動)

## 検証手順

### Phase 単位

各 phase は実装と同時にテストを書き、該当 test を pass させる。

### 統合検証 (= 全 phase 完了後)

1. **backend full test** — `pytest tests/` 全 green
2. **frontend build + test** — `npm run build` + `npm run test:ci`
3. **機能確認** — character catalog をモックして `build_screenplay` を呼び、`speaker_profiles` / 提案 `featured_characters` / `speaker_to_ref` が出力されること、実在しない ref が drop されることを確認
4. **graceful 確認** — catalog 空 / appearance 不在で `build_screenplay` が従来挙動になること
5. **schema roundtrip** — `speaker_profiles` を持つ abstract が `validate_abstract` を通ること

## 関連ドキュメント

- `docs/abstract-screenplay-design.md` — 抽象台本の設計。本機能で §3 のフィールド分類 (B / B') と §9 UI の更新が必要
- `docs/plannings/2026-05-12_legacy-schema-removal.md` — location_ref / camera_distance の analyze 自動選定。本機能はその catalog 注入パターンを casting に拡張するもの
